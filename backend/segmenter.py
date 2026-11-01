"""Energy-based utterance segmentation for loopback audio.

Loopback audio is digital (no room noise), so a simple adaptive energy gate is
enough to cut the stream into utterances: speech starts when a frame rises above
the noise floor and ends after a pause of `silence_ms`.
"""
from __future__ import annotations

from collections import deque

import numpy as np


class UtteranceSegmenter:
    def __init__(
        self,
        sample_rate: int = 16_000,
        frame_ms: int = 30,
        silence_ms: int = 750,
        min_speech_ms: int = 300,
        max_utterance_s: float = 25.0,
        preroll_ms: int = 300,
        min_rms: float = 0.0025,
        noise_factor: float = 1.5,
    ) -> None:
        self.frame_len = sample_rate * frame_ms // 1000
        self._silence_frames = max(1, silence_ms // frame_ms)
        self._min_speech_frames = max(1, min_speech_ms // frame_ms)
        self._max_frames = max(1, int(max_utterance_s * 1000 // frame_ms))
        self._preroll_frames = max(0, preroll_ms // frame_ms)
        self._min_rms = min_rms
        self._noise_factor = noise_factor
        self.reset()

    def reset(self) -> None:
        self._carry = np.zeros(0, dtype=np.float32)
        self._preroll: deque[np.ndarray] = deque(maxlen=self._preroll_frames)
        self._noise = 0.0
        self._clear_speech()

    def _clear_speech(self) -> None:
        self._in_speech = False
        self._buf: list[np.ndarray] = []
        self._speech_frames = 0
        self._silence = 0

    def feed(self, samples: np.ndarray) -> list[np.ndarray]:
        """Add 16 kHz mono float32 samples; return any finished utterances."""
        finished: list[np.ndarray] = []
        if samples.size == 0:
            return finished
        data = np.concatenate([self._carry, samples.astype(np.float32, copy=False)])
        n_frames = len(data) // self.frame_len
        for i in range(n_frames):
            frame = data[i * self.frame_len : (i + 1) * self.frame_len]
            utterance = self._process(frame)
            if utterance is not None:
                finished.append(utterance)
        self._carry = data[n_frames * self.frame_len :]
        return finished

    def _process(self, frame: np.ndarray) -> np.ndarray | None:
        rms = float(np.sqrt(np.mean(frame * frame)))
        threshold = max(self._min_rms, self._noise * self._noise_factor)

        if not self._in_speech:
            if rms > threshold:
                self._in_speech = True
                self._buf = [*self._preroll, frame]
                self._preroll.clear()
                self._speech_frames = 1
                self._silence = 0
            else:
                if rms <= self._min_rms:
                    self._noise = rms if self._noise == 0.0 else 0.95 * self._noise + 0.05 * rms
                self._preroll.append(frame)
            return None

        self._buf.append(frame)
        if rms > threshold * 0.7:  # hysteresis: do not chop on brief dips
            self._speech_frames += 1
            self._silence = 0
        else:
            self._silence += 1

        if self._silence >= self._silence_frames or len(self._buf) >= self._max_frames:
            return self._finish()
        return None

    def _finish(self) -> np.ndarray | None:
        audio = np.concatenate(self._buf)
        long_enough = self._speech_frames >= self._min_speech_frames
        self._clear_speech()
        return audio if long_enough else None
