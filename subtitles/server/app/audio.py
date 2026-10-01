from __future__ import annotations

import numpy as np


SAMPLE_RATE = 16_000


def pcm16_to_float32(pcm16: bytes) -> np.ndarray:
    if not pcm16 or len(pcm16) % 2:
        raise ValueError("expected non-empty, aligned PCM16")
    return np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0


def rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float32))))


class StreamingVad:
    """Low-cost gate used before Silero segments are passed to Whisper.

    Silero runs on candidate utterances; this gate prevents allocating a model
    task for silence and makes the streaming boundary deterministic.
    """

    def __init__(self, threshold: float = 0.008, trailing_silence_s: float = 0.6):
        self.threshold = threshold
        self.trailing_silence_s = trailing_silence_s
        self.silence_samples = 0
        self.speech_seen = False

    def observe(self, samples: np.ndarray) -> bool:
        if rms(samples) >= self.threshold:
            self.silence_samples = 0
            self.speech_seen = True
            return True
        self.silence_samples += len(samples)
        return False

    @property
    def reached_trailing_silence(self) -> bool:
        return self.silence_samples >= int(self.trailing_silence_s * SAMPLE_RATE)

    def reset(self) -> None:
        self.silence_samples = 0
        self.speech_seen = False
