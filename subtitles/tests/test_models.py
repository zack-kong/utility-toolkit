from pathlib import Path

import numpy as np
import pytest

from server.app.models import ModelRegistry


def test_text_translation_does_not_load_whisper(monkeypatch, tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path)
    monkeypatch.setattr(registry, "load_translation", lambda: None)
    monkeypatch.setattr(registry, "load", lambda: (_ for _ in ()).throw(AssertionError("Whisper loaded")))
    monkeypatch.setattr(registry._translator, "translate", lambda text, language, glossary, target, context, preset: "你好")
    assert registry.translate("Hello", "en") == "你好"


def test_unsupported_language_rejected_before_load(monkeypatch, tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path)
    monkeypatch.setattr(registry, "load_translation", lambda: (_ for _ in ()).throw(AssertionError("loaded")))
    with pytest.raises(ValueError, match="unsupported"):
        registry.translate("Hej", "sv")


def test_whisper_receives_only_bounded_context_and_hotwords(monkeypatch, tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path)
    received = {}

    class Whisper:
        def transcribe(self, audio, **kwargs):
            received.update(kwargs)
            return [type("Segment", (), {"text": "Hello"})()], type(
                "Info", (), {"language": "en", "language_probability": 0.99})()

    monkeypatch.setattr(registry, "load", lambda: None)
    registry._whisper = Whisper()  # type: ignore[assignment]
    result = registry.transcribe(np.ones(16000, dtype=np.float32), "fast", "en",
                                 "previous sentence", "Donald Duck")
    assert result.text == "Hello"
    assert received["initial_prompt"] == "previous sentence"
    assert received["hotwords"] == "Donald Duck"
    assert received["condition_on_previous_text"] is False


def test_term_pack_is_only_used_for_chinese_and_can_be_disabled(monkeypatch, tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path)
    presets = []
    monkeypatch.setattr(registry, "load_translation", lambda: None)
    monkeypatch.setattr(registry._translator, "translate",
                        lambda text, language, glossary, target, context, preset:
                        presets.append(preset) or "译文")
    registry.translate("Mickey Mouse", "en")
    registry.translate("Mickey Mouse", "en", term_pack_enabled=False)
    registry.translate("Mickey Mouse", "en", target_language="ja")
    assert ("Mickey Mouse", "米老鼠") in presets[0]
    assert presets[1:] == [(), ()]
