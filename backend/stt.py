"""Speech-to-text with Whisper (faster-whisper, runs locally)."""
from __future__ import annotations

import logging
import re
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)

# Whisper tends to invent these on near-silent or music-only audio.
_HALLUCINATIONS = {
    "you",
    "thank you",
    "thanks",
    "thanks for watching",
    "thank you for watching",
    "bye",
    "bye bye",
    "subtitles by the amara org community",
}


class Transcriber(Protocol):
    def load(self) -> None: ...

    def transcribe(self, audio: np.ndarray) -> str: ...


def clean_transcript(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    bare = re.sub(r"[^a-z ]", "", text.lower()).strip()
    if not bare or bare in _HALLUCINATIONS:
        return ""
    return text


class WhisperTranscriber:
    def __init__(self, model_size: str, device: str = "auto", compute_type: str = "auto", language: str = "en") -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._language = language or None
        self._model = None

    def load(self) -> None:
        """Load the model (downloads it on first use). Safe to call repeatedly."""
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster-whisper is not installed. Run: pip install faster-whisper") from exc
        log.info("Loading Whisper model '%s' ...", self._model_size)
        self._model = WhisperModel(self._model_size, device=self._device, compute_type=self._compute_type)
        log.info("Whisper model ready")

    def transcribe(self, audio: np.ndarray) -> str:
        if self._model is None:
            self.load()
        try:
            return self._transcribe_with_model(audio)
        except RuntimeError as exc:
            if self._device.lower() not in {"auto", "cuda"} or not _is_missing_cuda_library(exc):
                raise

            log.warning("CUDA libraries are unavailable; retrying Whisper transcription on CPU.")
            self._device = "cpu"
            self._compute_type = "int8"
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self._model_size, device=self._device, compute_type=self._compute_type)
            return self._transcribe_with_model(audio)

    def _transcribe_with_model(self, audio: np.ndarray) -> str:
        segments, _info = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            temperature=0.0,
        )
        parts = []
        for seg in segments:
            if seg.no_speech_prob > 0.8 and seg.avg_logprob < -1.0:
                continue
            parts.append(seg.text.strip())
        return clean_transcript(" ".join(parts))


def _is_missing_cuda_library(error: RuntimeError) -> bool:
    message = str(error).lower()
    return any(library in message for library in ("cublas", "cudnn", "cuda")) and any(
        detail in message for detail in ("not found", "cannot be loaded", "failed to load", "could not be loaded")
    )
