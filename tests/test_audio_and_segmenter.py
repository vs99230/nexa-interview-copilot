import numpy as np

from backend.audio_capture import TARGET_RATE, to_mono_16k
from backend.segmenter import UtteranceSegmenter
from backend.stt import clean_transcript


def tone(seconds: float, amp: float = 0.2) -> np.ndarray:
    t = np.arange(int(TARGET_RATE * seconds)) / TARGET_RATE
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(TARGET_RATE * seconds), dtype=np.float32)


def feed_in_chunks(seg: UtteranceSegmenter, audio: np.ndarray, chunk: int = 320):
    out = []
    for i in range(0, len(audio), chunk):
        out.extend(seg.feed(audio[i : i + chunk]))
    return out


def test_to_mono_16k_stereo_48k():
    stereo = (np.sin(np.linspace(0, 50, 9600)) * 10000).astype(np.int16)
    raw = np.repeat(stereo, 2).tobytes()  # 9600 frames, 2 channels, 48 kHz = 0.2 s
    out = to_mono_16k(raw, channels=2, rate=48_000)
    assert out.dtype == np.float32
    assert len(out) == 3200
    assert np.max(np.abs(out)) <= 1.0


def test_to_mono_16k_non_integer_ratio():
    raw = (np.sin(np.linspace(0, 80, 4410)) * 8000).astype(np.int16).tobytes()  # 0.1 s at 44.1 kHz
    out = to_mono_16k(raw, channels=1, rate=44_100)
    assert abs(len(out) - 1600) <= 1


def test_to_mono_16k_passthrough_and_empty():
    raw = np.zeros(160, dtype=np.int16).tobytes()
    assert len(to_mono_16k(raw, 1, 16_000)) == 160
    assert len(to_mono_16k(b"", 2, 48_000)) == 0


def test_segmenter_emits_one_utterance_after_pause():
    seg = UtteranceSegmenter(silence_ms=800)
    audio = np.concatenate([silence(0.5), tone(1.5), silence(1.2)])
    out = feed_in_chunks(seg, audio)
    assert len(out) == 1
    assert 1.5 <= len(out[0]) / TARGET_RATE <= 3.3  # speech + preroll + trailing pause


def test_segmenter_splits_two_utterances():
    seg = UtteranceSegmenter(silence_ms=800)
    audio = np.concatenate([tone(1.0), silence(1.2), tone(1.0), silence(1.2)])
    assert len(feed_in_chunks(seg, audio)) == 2


def test_segmenter_ignores_short_blips_and_silence():
    seg = UtteranceSegmenter(silence_ms=800, min_speech_ms=400)
    audio = np.concatenate([silence(1.0), tone(0.1), silence(1.5)])
    assert feed_in_chunks(seg, audio) == []


def test_segmenter_captures_quiet_speech():
    seg = UtteranceSegmenter(silence_ms=750)
    audio = np.concatenate([silence(0.5), tone(0.6, amp=0.004), silence(1.0)])

    out = feed_in_chunks(seg, audio)

    assert len(out) == 1
    assert abs(float(np.max(np.abs(out[0]))) - 0.004) < 0.0001


def test_segmenter_forces_cut_on_long_speech():
    seg = UtteranceSegmenter(max_utterance_s=2.0)
    out = feed_in_chunks(seg, tone(5.0))
    assert len(out) >= 2
    assert all(len(u) / TARGET_RATE <= 2.1 for u in out)


def test_segmenter_handles_odd_chunk_sizes():
    seg = UtteranceSegmenter(silence_ms=800)
    audio = np.concatenate([tone(1.0), silence(1.2)])
    out = []
    for i in range(0, len(audio), 777):
        out.extend(seg.feed(audio[i : i + 777]))
    assert len(out) == 1


def test_clean_transcript():
    assert clean_transcript("  Thank you. ") == ""
    assert clean_transcript("") == ""
    assert clean_transcript("Tell me   about\nyourself.") == "Tell me about yourself."
