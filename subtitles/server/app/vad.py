from __future__ import annotations

import numpy as np

from .audio import SAMPLE_RATE, rms


class SileroSpeechValidator:
    """Runs Silero on bounded candidate utterances, not on every PCM frame."""

    def __init__(self) -> None:
        self._model = None
        self._get_speech_timestamps = None

    def has_speech(self, samples: np.ndarray, audio_mode: str) -> bool:
        if audio_mode == "music":
            # Singing often fails speech VAD; Whisper gets the bounded window.
            return True
        if audio_mode == "vlog":
            # Speech under music/noise can fail Silero entirely. In this opt-in
            # mode, pass audible candidates to Whisper instead of losing them.
            return samples.size >= int(0.1 * SAMPLE_RATE) and rms(samples) >= 0.002
        if samples.size < int(0.1 * SAMPLE_RATE) or rms(samples) < 0.001:
            return False
        self._load()
        assert self._model is not None and self._get_speech_timestamps is not None
        try:
            import torch
            timestamps = self._get_speech_timestamps(
                torch.from_numpy(samples), self._model, sampling_rate=SAMPLE_RATE,
                threshold=0.35, min_speech_duration_ms=100,
            )
            return bool(timestamps)
        except Exception:
            # A VAD failure must not turn an audible sentence into silent data
            # loss. The streaming RMS gate above remains the conservative guard.
            return rms(samples) >= 0.012

    def _load(self) -> None:
        if self._model is not None:
            return
        from silero_vad import get_speech_timestamps, load_silero_vad
        self._model = load_silero_vad()
        self._get_speech_timestamps = get_speech_timestamps
