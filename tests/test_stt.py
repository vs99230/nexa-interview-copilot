import sys
from types import SimpleNamespace

import numpy as np
import pytest

from backend.stt import WhisperTranscriber


class Segment:
    text = " hello from cpu "
    no_speech_prob = 0.0
    avg_logprob = 0.0


def test_missing_cuda_library_retries_transcription_on_cpu(monkeypatch):
    models = []

    class FakeWhisperModel:
        def __init__(self, model_size, device, compute_type):
            self.device = device
            models.append((model_size, device, compute_type))

        def transcribe(self, audio, **kwargs):
            if self.device != "cpu":
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
            return iter([Segment()]), None

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel))
    transcriber = WhisperTranscriber("small", device="auto", compute_type="auto")

    assert transcriber.transcribe(np.zeros(1600, dtype=np.float32)) == "hello from cpu"
    assert models == [("small", "auto", "auto"), ("small", "cpu", "int8")]


def test_unrelated_transcription_runtime_error_is_not_retried_on_cpu(monkeypatch):
    models = []

    class FakeWhisperModel:
        def __init__(self, model_size, device, compute_type):
            models.append(device)

        def transcribe(self, audio, **kwargs):
            raise RuntimeError("invalid audio input")

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel))
    transcriber = WhisperTranscriber("small", device="auto", compute_type="auto")

    with pytest.raises(RuntimeError, match="invalid audio input"):
        transcriber.transcribe(np.zeros(1600, dtype=np.float32))
    assert models == ["auto"]
