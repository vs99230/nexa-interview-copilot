import asyncio
import io
import json

import httpx
import pytest

from backend.config import Settings
from backend.documents import DocumentError, extract_text
from backend.llm import LLMError, LLMRouter
from backend.session import InterviewSession


def sse(*payloads: dict, done: bool = False) -> bytes:
    body = "".join(f"data: {json.dumps(p)}\n\n" for p in payloads)
    return (body + ("data: [DONE]\n\n" if done else "")).encode()


def gemini_chunk(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def groq_chunk(text: str) -> dict:
    return {"choices": [{"delta": {"content": text}}]}


def make_router(handler, **settings_kw) -> LLMRouter:
    settings = Settings(
        gemini_api_key=settings_kw.get("gemini", "g-key"),
        groq_api_key=settings_kw.get("groq", "q-key"),
        gemini_models=("gem-a", "gem-b"),
        groq_models=("groq-a",),
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LLMRouter(settings, client=client)


async def collect(router, system="sys", messages=None):
    messages = messages or [{"role": "user", "content": "Tell me about yourself."}]
    return [e async for e in router.stream(system, messages)]


def test_gemini_success_streams_text_and_sends_key_in_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=sse(gemini_chunk("Hello "), gemini_chunk("there.")))

    events = asyncio.run(collect(make_router(handler)))
    assert "".join(e.text for e in events if e.kind == "delta") == "Hello there."
    assert seen["key"] == "g-key"
    assert "g-key" not in seen["url"]
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "sys"
    assert seen["body"]["contents"][0]["role"] == "user"


def test_falls_back_to_groq_when_gemini_fails():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "generativelanguage" in str(request.url):
            return httpx.Response(404, json={"error": "model retired"})
        return httpx.Response(200, content=sse(groq_chunk("From "), groq_chunk("Groq."), done=True))

    events = asyncio.run(collect(make_router(handler)))
    assert "".join(e.text for e in events) == "From Groq."
    assert events[0].provider == "groq"
    assert sum("generativelanguage" in c for c in calls) == 2  # both Gemini models tried


def test_dead_model_is_skipped_on_the_next_question():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "generativelanguage" in str(request.url):
            return httpx.Response(404, json={"error": "gone"})
        return httpx.Response(200, content=sse(groq_chunk("ok"), done=True))

    router = make_router(handler)
    asyncio.run(collect(router))
    calls.clear()
    asyncio.run(collect(router))
    assert calls and all("groq" in c for c in calls)


def test_mid_stream_failure_emits_reset_then_restarts():
    class DroppingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield sse(gemini_chunk("partial answer "))
            raise httpx.ReadError("connection dropped")

    def handler(request: httpx.Request) -> httpx.Response:
        if "generativelanguage" in str(request.url):
            return httpx.Response(200, stream=DroppingStream())
        return httpx.Response(200, content=sse(groq_chunk("Clean answer."), done=True))

    events = asyncio.run(collect(make_router(handler)))
    kinds = [e.kind for e in events]
    assert kinds.count("reset") == 2  # both Gemini models dropped mid-answer
    last_reset = len(kinds) - 1 - kinds[::-1].index("reset")
    assert "".join(e.text for e in events[last_reset + 1 :]) == "Clean answer."
    assert events[-1].provider == "groq"


def test_all_providers_failing_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(LLMError):
        asyncio.run(collect(make_router(handler)))


def test_no_keys_raises():
    router = make_router(lambda r: httpx.Response(200), gemini="", groq="")
    with pytest.raises(LLMError):
        asyncio.run(collect(router))


def test_session_prompt_history_and_clear():
    s = InterviewSession(history_turns=2)
    assert not s.has_context
    s.set_context("Resume: built RAG platform at Acme.", "JD: ML engineer, Python.")
    assert s.has_context
    prompt = s.build_system_prompt()
    assert "RAG platform" in prompt and "ML engineer" in prompt

    for i in range(3):
        s.add_turn(f"q{i}", f"a{i}")
    msgs = s.build_messages("q3")
    assert [m["content"] for m in msgs] == ["q1", "a1", "q2", "a2", "q3"]  # only last 2 turns kept
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant", "user"]

    s.clear_conversation()
    assert s.turns == []
    assert s.has_context  # resume/JD survive STOP


def test_extract_text_txt_docx_pdf_and_errors():
    assert "Python" in extract_text("cv.txt", b"Vaibhav built a Python service for data pipelines in prod.")

    from docx import Document

    doc = Document()
    doc.add_paragraph("Experience: Data Scientist intern building forecasting models.")
    buf = io.BytesIO()
    doc.save(buf)
    assert "forecasting" in extract_text("cv.docx", buf.getvalue())

    with pytest.raises(DocumentError):
        extract_text("cv.exe", b"x")
    with pytest.raises(DocumentError):
        extract_text("cv.txt", b"too short")
    with pytest.raises(DocumentError):
        extract_text("broken.pdf", b"not really a pdf")
