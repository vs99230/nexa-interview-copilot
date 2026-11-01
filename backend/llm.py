"""LLM router: Gemini first, Groq as fallback. Streams plain-text deltas.

Failure handling:
  * A model that fails before producing text is skipped and the next one is tried.
  * A model that fails mid-answer yields a "reset" event (the UI clears the partial
    answer) and the next model restarts the answer.
  * Models that return auth/not-found errors are put on a 10-minute cool-down, and
    rate-limit/server/network errors on a 30-second cool-down, so later questions do
    not waste time on a dead model.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable

import httpx

from .config import Settings

log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

HARD_FAIL_STATUSES = {400, 401, 403, 404}
HARD_COOLDOWN_S = 600.0
SOFT_COOLDOWN_S = 30.0


class LLMError(RuntimeError):
    """Every configured provider failed."""


class ProviderError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class LLMEvent:
    kind: str  # "delta" | "reset"
    text: str = ""
    provider: str = ""


@dataclass(frozen=True)
class Attempt:
    provider: str
    model: str

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


async def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        body = (await resp.aread()).decode("utf-8", errors="replace")[:300]
        raise ProviderError(f"HTTP {resp.status_code}: {body}", resp.status_code)


async def _sse_json(resp: httpx.Response) -> AsyncIterator[dict]:
    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            continue


class LLMRouter:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)
        )
        self._clock = clock
        self._blocked_until: dict[str, float] = {}
        self.attempts: list[Attempt] = []
        if settings.gemini_api_key:
            self.attempts += [Attempt("gemini", m) for m in settings.gemini_models]
        if settings.groq_api_key:
            self.attempts += [Attempt("groq", m) for m in settings.groq_models]

    async def aclose(self) -> None:
        await self._client.aclose()

    async def stream(self, system: str, messages: list[dict[str, str]]) -> AsyncIterator[LLMEvent]:
        if not self.attempts:
            raise LLMError("No LLM API key configured. Set GEMINI_API_KEY and/or GROQ_API_KEY in .env.")

        now = self._clock()
        candidates = [a for a in self.attempts if self._blocked_until.get(a.key, 0.0) <= now]
        if not candidates:  # everything is cooling down: try anyway
            candidates = list(self.attempts)

        failures: list[str] = []
        for attempt in candidates:
            emitted = False
            try:
                async for piece in self._call(attempt, system, messages):
                    emitted = True
                    yield LLMEvent("delta", piece, attempt.provider)
                if emitted:
                    return
                raise ProviderError("empty response")
            except ProviderError as exc:
                cooldown = HARD_COOLDOWN_S if exc.status in HARD_FAIL_STATUSES else SOFT_COOLDOWN_S
                failures.append(f"{attempt.key}: {exc}")
            except httpx.HTTPError as exc:
                cooldown = SOFT_COOLDOWN_S
                failures.append(f"{attempt.key}: {type(exc).__name__} {exc}")

            self._blocked_until[attempt.key] = self._clock() + cooldown
            log.warning("LLM attempt failed - %s", failures[-1])
            if emitted:
                yield LLMEvent("reset", provider=attempt.provider)

        raise LLMError("All LLM providers failed. " + " | ".join(failures)[:400])

    def _call(self, attempt: Attempt, system: str, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        if attempt.provider == "gemini":
            return self._gemini(attempt.model, system, messages)
        return self._groq(attempt.model, system, messages)

    async def _gemini(self, model: str, system: str, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages
            ],
            "generationConfig": {"temperature": 0.6, "maxOutputTokens": 1024},
        }
        headers = {"x-goog-api-key": self._settings.gemini_api_key}
        async with self._client.stream("POST", GEMINI_URL.format(model=model), json=body, headers=headers) as resp:
            await _raise_for_status(resp)
            async for payload in _sse_json(resp):
                for candidate in payload.get("candidates", []):
                    for part in (candidate.get("content") or {}).get("parts", []):
                        text = part.get("text")
                        if text and not part.get("thought"):
                            yield text

    async def _groq(self, model: str, system: str, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": True,
            "temperature": 0.6,
            "max_tokens": 1000,
        }
        headers = {"Authorization": f"Bearer {self._settings.groq_api_key}"}
        async with self._client.stream("POST", GROQ_URL, json=body, headers=headers) as resp:
            await _raise_for_status(resp)
            async for payload in _sse_json(resp):
                for choice in payload.get("choices", []):
                    text = (choice.get("delta") or {}).get("content")
                    if text:
                        yield text
