import numpy as np
import pytest

from server.app.audio import SAMPLE_RATE, StreamingVad, pcm16_to_float32, rms


def test_pcm16_conversion_and_rms() -> None:
    samples = pcm16_to_float32(np.array([-32768, 0, 32767], dtype="<i2").tobytes())
    assert np.allclose(samples, [-1.0, 0.0, 32767 / 32768])
    assert rms(samples) > 0.5


def test_pcm16_rejects_empty_and_misaligned() -> None:
    with pytest.raises(ValueError):
        pcm16_to_float32(b"")
    with pytest.raises(ValueError):
        pcm16_to_float32(b"x")


def test_streaming_vad_marks_trailing_silence() -> None:
    vad = StreamingVad(threshold=0.01, trailing_silence_s=0.1)
    assert vad.observe(np.full(320, 0.1, dtype=np.float32))
    for _ in range(5):
        assert not vad.observe(np.zeros(320, dtype=np.float32))
    assert vad.reached_trailing_silence
    vad.reset()
    assert not vad.speech_seen
    assert SAMPLE_RATE == 16000
