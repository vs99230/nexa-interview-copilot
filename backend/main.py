"""FastAPI app: REST for setup/start/stop, WebSocket for live events, serves the UI."""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import Callable
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .audio_capture import WasapiLoopbackCapture
from .config import FRONTEND_DIST, Settings
from .documents import MAX_UPLOAD_BYTES, DocumentError, extract_text
from .hub import Hub
from .llm import LLMRouter
from .pipeline import Pipeline, PipelineBusy
from .session import InterviewSession
from .stt import WhisperTranscriber

log = logging.getLogger("nexa")

PipelineFactory = Callable[[Settings, Hub, InterviewSession], Pipeline]
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
MIN_RESUME_CHARS = 30
MIN_JD_CHARS = 20


def default_pipeline_factory(settings: Settings, hub: Hub, session: InterviewSession) -> Pipeline:
    return Pipeline(
        settings=settings,
        hub=hub,
        session=session,
        router=LLMRouter(settings),
        transcriber=WhisperTranscriber(
            settings.whisper_model, settings.whisper_device, settings.whisper_compute_type, settings.whisper_language
        ),
        capture_factory=lambda on_audio: WasapiLoopbackCapture(on_audio),
    )


def _origin_ok(origin: str | None) -> bool:
    """Reject requests that come from a web page on another site (CSRF / DNS rebinding)."""
    if not origin:
        return True
    return urlparse(origin).hostname in _LOCAL_HOSTS


def create_app(settings: Settings | None = None, pipeline_factory: PipelineFactory | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    hub = Hub()
    session = InterviewSession(history_turns=settings.history_turns)
    pipeline = (pipeline_factory or default_pipeline_factory)(settings, hub, session)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await pipeline.stop()

    app = FastAPI(title="Nexa Interview Copilot", lifespan=lifespan)

    @app.middleware("http")
    async def guard_state_changes(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if not _origin_ok(request.headers.get("origin")) or request.headers.get("x-nexa-client") != "1":
                return JSONResponse({"detail": "Forbidden"}, status_code=403)
        return await call_next(request)

    def snapshot() -> dict:
        return {
            "state": pipeline.state,
            "has_context": session.has_context,
            "resume_chars": len(session.resume_text),
            "jd_chars": len(session.job_description),
            "llm_providers": settings.provider_names,
            "whisper_model": settings.whisper_model,
            "audio_supported": sys.platform == "win32",
        }

    @app.get("/api/status")
    def status() -> dict:
        return snapshot()

    @app.post("/api/context")
    async def set_context(
        resume: UploadFile | None = File(None),
        resume_text: str = Form(""),
        job_description: str = Form(""),
    ) -> dict:
        if pipeline.state != "idle":
            raise HTTPException(409, "Stop the current session before changing the resume or job description.")

        text = resume_text.strip()
        if resume is not None and resume.filename:
            data = await resume.read(MAX_UPLOAD_BYTES + 1)
            if len(data) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "Resume file is larger than 5 MB.")
            try:
                text = extract_text(resume.filename, data)
            except DocumentError as exc:
                raise HTTPException(400, str(exc)) from exc

        if len(text) < MIN_RESUME_CHARS:
            raise HTTPException(400, "Upload a resume (PDF, DOCX or TXT) or paste its text.")
        if len(job_description.strip()) < MIN_JD_CHARS:
            raise HTTPException(400, "Paste the job description.")

        session.set_context(text, job_description)
        return snapshot()

    @app.post("/api/start")
    async def start() -> dict:
        if not session.has_context:
            raise HTTPException(400, "Upload the resume and job description first.")
        if not settings.has_llm_key:
            raise HTTPException(400, "No LLM key found. Add GEMINI_API_KEY and/or GROQ_API_KEY to the .env file.")
        try:
            await pipeline.start()
        except PipelineBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        return snapshot()

    @app.post("/api/stop")
    async def stop() -> dict:
        await pipeline.stop()
        return snapshot()

    @app.websocket("/ws")
    async def events(ws: WebSocket) -> None:
        if not _origin_ok(ws.headers.get("origin")):
            await ws.close(code=1008)
            return
        await hub.connect(ws)
        try:
            await ws.send_json({"type": "status", "state": pipeline.state})
            while True:
                await ws.receive_text()  # the UI never sends; this just detects disconnects
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(ws)

    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")
    else:

        @app.get("/")
        def no_ui() -> dict:
            return {"detail": "Frontend not built. Run: cd frontend && npm install && npm run build"}

    app.state.pipeline = pipeline
    app.state.session = session
    return app


def run_dev() -> None:
    """`python -m backend.main` - API only, for use with the Vite dev server."""
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(create_app(), host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    run_dev()
