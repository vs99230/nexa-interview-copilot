import asyncio

import numpy as np
from fastapi.testclient import TestClient

from backend.audio_capture import TARGET_RATE
from backend.config import Settings
from backend.llm import LLMError, LLMEvent
from backend.main import create_app
from backend.pipeline import Pipeline
from backend.session import InterviewSession

HEADERS = {"X-Nexa-Client": "1"}
RESUME = "Vaibhav Singh - Data Scientist intern. Built an AI document RAG platform and anomaly detection system."
JD = "We are hiring an ML engineer with Python, NLP and RAG experience."


def tone(seconds, amp=0.2):
    t = np.arange(int(TARGET_RATE * seconds)) / TARGET_RATE
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


class RecordingHub:
    def __init__(self):
        self.events = []

    async def broadcast(self, event):
        self.events.append(event)

    def types(self):
        return [e["type"] for e in self.events]


class FakeTranscriber:
    def __init__(self, texts):
        self.texts = list(texts)
        self.loaded = False

    def load(self):
        self.loaded = True

    def transcribe(self, audio):
        return self.texts.pop(0) if self.texts else ""


class FakeCapture:
    instances = []

    def __init__(self, on_audio):
        self.on_audio = on_audio
        self.started = self.stopped = False
        FakeCapture.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class FakeRouter:
    def __init__(self, fail=False):
        self.fail = fail
        self.seen_messages = []

    async def stream(self, system, messages):
        self.seen_messages.append(messages)
        if self.fail:
            raise LLMError("all providers failed")
        for piece in ("I built ", "a RAG platform."):
            yield LLMEvent("delta", piece, "fake")


async def wait_for(predicate, timeout=5.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        assert loop.time() < end, "timed out waiting for condition"
        await asyncio.sleep(0.02)


def build(texts, fail=False):
    hub = RecordingHub()
    session = InterviewSession()
    session.set_context(RESUME, JD)
    router = FakeRouter(fail=fail)
    transcriber = FakeTranscriber(texts)
    FakeCapture.instances.clear()
    pipe = Pipeline(Settings(gemini_api_key="x"), hub, session, router, transcriber, FakeCapture)
    return pipe, hub, session, router, transcriber


def speak(pipe, seconds=1.2):
    capture = FakeCapture.instances[-1]
    audio = np.concatenate([tone(seconds), np.zeros(int(TARGET_RATE * 1.2), dtype=np.float32)])
    for i in range(0, len(audio), 320):
        capture.on_audio(audio[i : i + 320])


def test_full_flow_question_to_answer_then_stop_clears_memory():
    async def scenario():
        pipe, hub, session, router, transcriber = build(["Tell me about your RAG project.", "Why did you pick it?"])
        await pipe.start()
        await wait_for(lambda: pipe.state == "listening")
        assert transcriber.loaded and FakeCapture.instances[-1].started

        speak(pipe)
        await wait_for(lambda: "answer_done" in hub.types())
        assert [e["text"] for e in hub.events if e["type"] == "question"] == ["Tell me about your RAG project."]
        assert "".join(e["text"] for e in hub.events if e["type"] == "answer_delta") == "I built a RAG platform."
        assert len(session.turns) == 1

        speak(pipe)  # follow-up carries the earlier turn as context
        await wait_for(lambda: hub.types().count("answer_done") == 2)
        assert [m["content"] for m in router.seen_messages[1]][-1] == "Why did you pick it?"
        assert len(router.seen_messages[1]) == 3

        await pipe.stop()
        assert pipe.state == "idle"
        assert session.turns == [] and session.has_context
        assert FakeCapture.instances[-1].stopped
        assert "stopped" in hub.types()

    asyncio.run(scenario())


def test_statements_do_not_trigger_answers():
    async def scenario():
        pipe, hub, session, *_ = build(["Thanks for joining us today."])
        await pipe.start()
        await wait_for(lambda: pipe.state == "listening")
        speak(pipe)
        await wait_for(lambda: "heard" in hub.types())
        await asyncio.sleep(0.3)
        assert "question" not in hub.types()
        await pipe.stop()

    asyncio.run(scenario())


def test_llm_failure_reports_error_and_keeps_listening():
    async def scenario():
        pipe, hub, session, *_ = build(["What is a vector database?"], fail=True)
        await pipe.start()
        await wait_for(lambda: pipe.state == "listening")
        speak(pipe)
        await wait_for(lambda: "answer_error" in hub.types())
        await wait_for(lambda: pipe.state == "listening")
        assert session.turns == []
        await pipe.stop()

    asyncio.run(scenario())


def test_capture_failure_returns_to_idle_with_error():
    class BadCapture(FakeCapture):
        def start(self):
            raise RuntimeError("no loopback device")

    async def scenario():
        pipe, hub, *_ = build([])
        pipe.capture_factory = BadCapture
        await pipe.start()
        await wait_for(lambda: pipe.state == "idle")
        errors = [e for e in hub.events if e["type"] == "error"]
        assert errors and "no loopback device" in errors[0]["message"]

    asyncio.run(scenario())


def test_stop_without_start_is_safe():
    async def scenario():
        pipe, hub, *_ = build([])
        await pipe.stop()
        assert pipe.state == "idle"

    asyncio.run(scenario())


# ------------------------------------------------------------------ REST / WS


def make_client():
    FakeCapture.instances.clear()
    settings = Settings(gemini_api_key="x")

    def factory(settings, hub, session):
        return Pipeline(settings, hub, session, FakeRouter(), FakeTranscriber([]), FakeCapture)

    return TestClient(create_app(settings, factory))


def test_api_context_validation_and_start_flow():
    with make_client() as client:
        assert client.get("/api/status").json()["has_context"] is False

        r = client.post("/api/start", headers=HEADERS)
        assert r.status_code == 400  # no context yet

        r = client.post("/api/context", headers=HEADERS, data={"resume_text": "short", "job_description": JD})
        assert r.status_code == 400

        r = client.post("/api/context", headers=HEADERS, data={"resume_text": RESUME, "job_description": ""})
        assert r.status_code == 400

        r = client.post(
            "/api/context",
            headers=HEADERS,
            files={"resume": ("cv.txt", RESUME.encode(), "text/plain")},
            data={"job_description": JD},
        )
        assert r.status_code == 200 and r.json()["has_context"] is True

        r = client.post("/api/start", headers=HEADERS)
        assert r.status_code == 200

        r = client.post("/api/context", headers=HEADERS, data={"resume_text": RESUME, "job_description": JD})
        assert r.status_code == 409  # cannot change context mid-session

        assert client.post("/api/stop", headers=HEADERS).json()["state"] == "idle"


def test_api_rejects_unsafe_origin_and_missing_header():
    with make_client() as client:
        assert client.post("/api/stop").status_code == 403  # no X-Nexa-Client header
        evil = {**HEADERS, "Origin": "https://evil.example"}
        assert client.post("/api/stop", headers=evil).status_code == 403
        ok = {**HEADERS, "Origin": "http://localhost:5173"}
        assert client.post("/api/stop", headers=ok).status_code == 200


def test_api_start_requires_llm_key():
    FakeCapture.instances.clear()
    settings = Settings()  # no keys

    def factory(settings, hub, session):
        return Pipeline(settings, hub, session, FakeRouter(), FakeTranscriber([]), FakeCapture)

    with TestClient(create_app(settings, factory)) as client:
        client.post("/api/context", headers=HEADERS, data={"resume_text": RESUME, "job_description": JD})
        r = client.post("/api/start", headers=HEADERS)
        assert r.status_code == 400 and "GEMINI_API_KEY" in r.json()["detail"]


def test_websocket_snapshot_and_origin_check():
    with make_client() as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json() == {"type": "status", "state": "idle"}
        try:
            with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as ws:
                ws.receive_json()
            raised = False
        except Exception:
            raised = True
        assert raised
