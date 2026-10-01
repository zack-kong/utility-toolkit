import json
from pathlib import Path

from server.app.hy_translate import HyTranslator


def test_local_translation_request_uses_auth_and_translation_prompt(monkeypatch, tmp_path: Path) -> None:
    translator = HyTranslator(tmp_path / "model.gguf", tmp_path / "llama-server.exe", "secret")
    monkeypatch.setattr(translator, "ensure_ready", lambda: None)
    observed = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    def fake_urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["auth"] = request.get_header("Authorization")
        observed["body"] = json.loads(request.data)
        assert timeout == 45
        return Response()

    monkeypatch.setattr("server.app.hy_translate.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("server.app.hy_translate.json.load", lambda response: {
        "choices": [{"message": {"content": "  再来一次！  "}}],
    })
    assert translator.translate("もう一回やって！") == "再来一次！"
    assert observed["url"] == "http://127.0.0.1:8766/v1/chat/completions"
    assert observed["auth"] == "Bearer secret"
    assert "Output only the translation" in observed["body"]["messages"][0]["content"]


def test_japanese_name_hint_is_included_only_when_source_matches(monkeypatch, tmp_path: Path) -> None:
    translator = HyTranslator(tmp_path / "model.gguf", tmp_path / "llama-server.exe", "secret")
    monkeypatch.setattr(translator, "ensure_ready", lambda: None)
    prompts = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    def fake_urlopen(request, timeout):
        prompts.append(json.loads(request.data)["messages"][0]["content"])
        return Response()

    monkeypatch.setattr("server.app.hy_translate.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("server.app.hy_translate.json.load", lambda response: {
        "choices": [{"message": {"content": "唐老鸭来了"}}],
    })
    translator.translate("ドナルド・ダックが来た", "ja")
    translator.translate("ドナルドが来た", "ja")
    assert "ドナルド・ダック → 唐老鸭" in prompts[0]
    assert prompts[0].index("Use these established names") < prompts[0].index("Translate the current text") < prompts[0].rindex("ドナルド・ダックが来た")
    assert "Use these established names" not in prompts[1]


def test_exact_canonical_name_skips_model_call(tmp_path: Path) -> None:
    translator = HyTranslator(tmp_path / "missing.gguf", tmp_path / "missing.exe", "secret")
    assert translator.translate("ドナルド・ダック", "ja") == "唐老鸭"
    assert translator.translate("ドナルド", "ja", "ja|ドナルド = 唐老鸭") == "唐老鸭"


def test_non_chinese_target_uses_target_prompt_without_chinese_glossary(monkeypatch, tmp_path: Path) -> None:
    translator = HyTranslator(tmp_path / "model.gguf", tmp_path / "llama-server.exe", "secret")
    monkeypatch.setattr(translator, "ensure_ready", lambda: None)
    prompts = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    def fake_urlopen(request, timeout):
        prompts.append(json.loads(request.data)["messages"][0]["content"])
        return Response()

    monkeypatch.setattr("server.app.hy_translate.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("server.app.hy_translate.json.load", lambda response: {
        "choices": [{"message": {"content": "Donald Duck is here."}}],
    })
    assert translator.translate("ドナルド・ダックが来た", "ja", target_language="en",
                                context="さっきは友達の話をした。") == "Donald Duck is here."
    assert "into English" in prompts[0]
    assert "唐老鸭" not in prompts[0]
    assert "infer the current topic" in prompts[0]
    assert "Do not invent speech" in prompts[0]
    assert prompts[0].endswith("ドナルド・ダックが来た")
