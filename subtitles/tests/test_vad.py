import numpy as np
import torch

from server.app.vad import SileroSpeechValidator


def test_silero_receives_tensor() -> None:
    validator = SileroSpeechValidator()
    validator._model = object()
    observed = []

    def fake_silero(audio, model, sampling_rate, threshold, min_speech_duration_ms):
        observed.append((isinstance(audio, torch.Tensor), sampling_rate,
                         threshold, min_speech_duration_ms))
        return [{"start": 0, "end": 4000}]

    validator._get_speech_timestamps = fake_silero
    short_quiet_speech = np.concatenate((
        np.zeros(4800, dtype=np.float32),
        np.full(1920, 0.006, dtype=np.float32),
        np.zeros(9600, dtype=np.float32),
    ))
    assert validator.has_speech(short_quiet_speech, "dialogue")
    assert validator.has_speech(np.full(3200, 0.02, dtype=np.float32), "dialogue")
    assert observed == [(True, 16000, 0.35, 100)] * 2
