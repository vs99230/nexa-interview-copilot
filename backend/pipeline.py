"""Orchestrates: system audio -> utterance -> Whisper -> question -> LLM answer -> UI.

One audio input becomes one detected question becomes one streamed answer.
Questions are answered strictly one at a time; if the interviewer keeps talking,
new questions wait in a small queue (the oldest is dropped when it overflows).
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Callable, Protocol

import numpy as np

from .audio_capture import TARGET_RATE, AudioCallback
from .config import Settings
from .hub import Hub
from .llm import LLMError
from .question_detector import QuestionDetector
from .segmenter import UtteranceSegmenter
from .session import InterviewSession
from .stt import Transcriber

log = logging.getLogger(__name__)


class PipelineBusy(RuntimeError):
    """start() was called while a session is already running."""


class Capture(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


class Router(Protocol):
    def stream(self, system: str, messages: list[dict[str, str]]): ...


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        hub: Hub,
        session: InterviewSession,
        router: Router,
        transcriber: Transcriber,
        capture_factory: Callable[[AudioCallback], Capture],
    ) -> None:
        self.settings = settings
        self.hub = hub
        self.session = session
        self.router = router
        self.transcriber = transcriber
        self.capture_factory = capture_factory
        self.segmenter = UtteranceSegmenter(silence_ms=settings.silence_ms)
        self.detector = QuestionDetector()

        self.state = "idle"  # idle | starting | listening | answering
        self._loop: asyncio.AbstractEventLoop | None = None
        self._capture: Capture | None = None
        self._boot_task: asyncio.Task | None = None
        self._tasks: list[asyncio.Task] = []
        self._utterances: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=8)
        self._questions: asyncio.Queue[str] = asyncio.Queue(maxsize=4)

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        if self.state != "idle":
            raise PipelineBusy("A session is already running.")
        await self._set_state("starting")
        self._boot_task = asyncio.create_task(self._boot())

    async def stop(self) -> None:
        """Stop listening and wipe the temporary conversation memory."""
        was_idle = self.state == "idle" and self._boot_task is None
        await self._teardown()
        self.session.clear_conversation()
        self.detector.reset()
        self.segmenter.reset()
        await self.hub.broadcast({"type": "stopped"})
        if not was_idle or self.state != "idle":
            await self._set_state("idle")

    async def _boot(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            self._loop = loop
            await loop.run_in_executor(None, self.transcriber.load)  # may download the model
            self.segmenter.reset()
            self.detector.reset()
            self._utterances = asyncio.Queue(maxsize=8)
            self._questions = asyncio.Queue(maxsize=4)
            capture = self.capture_factory(self._on_audio_threadsafe)
            capture.start()
            self._capture = capture
            self._tasks = [asyncio.create_task(self._stt_loop()), asyncio.create_task(self._answer_loop())]
            await self._set_state("listening")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Failed to start the session")
            await self._teardown()
            await self.hub.broadcast({"type": "error", "message": str(exc)})
            await self._set_state("idle")

    async def _teardown(self) -> None:
        tasks = [t for t in [self._boot_task, *self._tasks] if t is not None and t is not asyncio.current_task()]
        self._boot_task = None
        self._tasks = []
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        capture, self._capture = self._capture, None
        if capture is not None:
            await asyncio.get_running_loop().run_in_executor(None, capture.stop)

    async def _set_state(self, state: str) -> None:
        self.state = state
        await self.hub.broadcast({"type": "status", "state": state})

    # ------------------------------------------------------------------- audio

    def _on_audio_threadsafe(self, chunk: np.ndarray) -> None:
        """Called from the audio thread."""
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._ingest, chunk)

    def _ingest(self, chunk: np.ndarray) -> None:
        for utterance in self.segmenter.feed(chunk):
            _put_drop_oldest(self._utterances, utterance, "audio")

    async def _stt_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                audio = await asyncio.wait_for(self._utterances.get(), timeout=0.5)
            except asyncio.TimeoutError:
                for question in self.detector.poll(time.monotonic()):
                    _put_drop_oldest(self._questions, question)
                continue

            audio_seconds = len(audio) / TARGET_RATE
            started_at = time.perf_counter()
            try:
                text = await loop.run_in_executor(None, self.transcriber.transcribe, audio)
            except Exception:
                log.exception("Transcription failed")
                await self.hub.broadcast({"type": "error", "message": "Transcription failed for one segment."})
                continue
            elapsed = time.perf_counter() - started_at
            if elapsed > audio_seconds:
                log.warning(
                    "Transcription took %.1fs for %.1fs of audio; the recognizer may be falling behind.",
                    elapsed,
                    audio_seconds,
                )
            if not text:
                continue

            await self.hub.broadcast({"type": "heard", "text": text})
            for question in self.detector.feed(text, time.monotonic()):
                _put_drop_oldest(self._questions, question, "question")

    # ----------------------------------------------------------------- answers

    async def _answer_loop(self) -> None:
        while True:
            question = await self._questions.get()
            qid = uuid.uuid4().hex[:8]
            await self.hub.broadcast({"type": "question", "id": qid, "text": question})
            await self._set_state("answering")
            try:
                await self._answer(qid, question)
            finally:
                if self.state == "answering":
                    await self._set_state("listening")

    async def _answer(self, qid: str, question: str) -> None:
        parts: list[str] = []
        try:
            async for event in self.router.stream(
                self.session.build_system_prompt(), self.session.build_messages(question)
            ):
                if event.kind == "reset":
                    parts.clear()
                    await self.hub.broadcast({"type": "answer_reset", "id": qid})
                else:
                    parts.append(event.text)
                    await self.hub.broadcast({"type": "answer_delta", "id": qid, "text": event.text})
        except asyncio.CancelledError:
            raise
        except LLMError as exc:
            await self.hub.broadcast({"type": "answer_error", "id": qid, "message": str(exc)})
            return
        except Exception:
            log.exception("Unexpected error while generating an answer")
            await self.hub.broadcast({"type": "answer_error", "id": qid, "message": "Unexpected error while answering."})
            return

        answer = "".join(parts).strip()
        self.session.add_turn(question, answer)
        await self.hub.broadcast({"type": "answer_done", "id": qid})


def _put_drop_oldest(queue: asyncio.Queue, item, queue_name: str = "item") -> None:
    while True:
        try:
            queue.put_nowait(item)
            return
        except asyncio.QueueFull:
            log.warning("The %s queue is full; dropping its oldest item.", queue_name)
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
