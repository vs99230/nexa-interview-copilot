"""System-audio capture through Windows WASAPI loopback.

Loopback records what the default output device is playing (the interviewer's
voice from a call app), not the microphone. Audio is converted to mono float32
at 16 kHz, which is what Whisper expects.
"""
from __future__ import annotations

import logging
import sys
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

TARGET_RATE = 16_000
AudioCallback = Callable[[np.ndarray], None]


class AudioCaptureError(RuntimeError):
    """System audio could not be captured."""


def to_mono_16k(raw: bytes, channels: int, rate: int) -> np.ndarray:
    """Convert interleaved int16 PCM bytes to mono float32 at 16 kHz."""
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        usable = len(samples) - len(samples) % channels
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)
    if rate == TARGET_RATE or samples.size == 0:
        return samples.astype(np.float32, copy=False)

    if rate % TARGET_RATE == 0:
        factor = rate // TARGET_RATE
        usable = len(samples) - len(samples) % factor
        return samples[:usable].reshape(-1, factor).mean(axis=1).astype(np.float32)

    # Non-integer ratio (e.g. 44.1 kHz): crude low-pass, then linear resample.
    width = max(1, round(rate / TARGET_RATE))
    if width > 1:
        samples = np.convolve(samples, np.ones(width, dtype=np.float32) / width, mode="same")
    n_out = int(len(samples) * TARGET_RATE / rate)
    if n_out == 0:
        return np.zeros(0, dtype=np.float32)
    old_t = np.linspace(0.0, 1.0, len(samples), endpoint=False)
    new_t = np.linspace(0.0, 1.0, n_out, endpoint=False)
    return np.interp(new_t, old_t, samples).astype(np.float32)


class WasapiLoopbackCapture:
    """Streams the default speakers' output to `on_audio` from a PortAudio thread."""

    def __init__(self, on_audio: AudioCallback) -> None:
        self._on_audio = on_audio
        self._pa = None
        self._stream = None

    def start(self) -> None:
        if sys.platform != "win32":
            raise AudioCaptureError("System-audio capture needs Windows (WASAPI loopback).")
        try:
            import pyaudiowpatch as pyaudio
        except ImportError as exc:
            raise AudioCaptureError("PyAudioWPatch is not installed. Run: pip install PyAudioWPatch") from exc

        pa = pyaudio.PyAudio()
        try:
            device = self._find_loopback_device(pa, pyaudio)
            channels = int(device["maxInputChannels"])
            rate = int(device["defaultSampleRate"])

            def callback(in_data, frame_count, time_info, status):  # PortAudio thread
                try:
                    self._on_audio(to_mono_16k(in_data, channels, rate))
                except Exception:
                    log.exception("Audio callback failed")
                return (None, pyaudio.paContinue)

            self._stream = pa.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                frames_per_buffer=rate // 50,  # 20 ms
                input_device_index=int(device["index"]),
                stream_callback=callback,
            )
        except AudioCaptureError:
            pa.terminate()
            raise
        except Exception as exc:
            pa.terminate()
            raise AudioCaptureError(f"Could not open the loopback device: {exc}") from exc

        self._pa = pa
        log.info("Capturing system audio from '%s' (%d ch, %d Hz)", device["name"], channels, rate)

    @staticmethod
    def _find_loopback_device(pa, pyaudio) -> dict:
        try:
            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError as exc:
            raise AudioCaptureError("WASAPI is not available on this system.") from exc

        speakers = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        if speakers.get("isLoopbackDevice"):
            return speakers
        for loopback in pa.get_loopback_device_info_generator():
            if speakers["name"] in loopback["name"]:
                return loopback
        raise AudioCaptureError(
            f"No loopback device found for the default speakers ('{speakers['name']}'). "
            "Check that an output device is enabled in Windows Sound settings."
        )

    def stop(self) -> None:
        stream, pa = self._stream, self._pa
        self._stream = self._pa = None
        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                log.exception("Error while closing the audio stream")
        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                log.exception("Error while terminating PortAudio")
