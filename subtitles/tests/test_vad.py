import numpy as np
import torch

from server.app.vad import SileroSpeechValidator


def test_silero_receives_tensor() -> None:
    validator = SileroSpeechValidator()
    validator._model = object()
    observed = []

    def fake_silero(audio, model, sampling_rate):
        observed.append((isinstance(audio, torch.Tensor), sampling_rate))
        return [{"start": 0, "end": 4000}]

    validator._get_speech_timestamps = fake_silero
    assert validator.has_speech(np.full(8000, 0.1, dtype=np.float32), "dialogue")
    assert observed == [(True, 16000)]
