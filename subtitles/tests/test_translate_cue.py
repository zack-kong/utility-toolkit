import asyncio
import json

import pytest
from fastapi import HTTPException

from server.app import main


class DummySettings:
    def token(self) -> str:
        return "test-token"


def test_translate_cue_rejects_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "settings", DummySettings())
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.translate_cue({"text": "Hello", "language": "en"}, None))
    assert error.value.status_code == 401


def test_translate_cue_uses_track_language_and_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "settings", DummySettings())
    monkeypatch.setattr(main.models, "translate", lambda text, language, glossary, target, context, enabled: f"{language}:{text}")
    result = asyncio.run(main.translate_cue({"text": "Hello", "language": "en-US"}, "test-token"))
    assert result == {"translation": "en:Hello"}
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.translate_cue({"text": "Hello", "language": "xx"}, "test-token"))
    assert error.value.status_code == 400


def test_translate_cue_passes_custom_glossary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "settings", DummySettings())
    received = []
    monkeypatch.setattr(main.models, "translate", lambda text, language, glossary, target, context, enabled:
                        received.append((text, language, glossary, target)) or "唐老鸭")
    result = asyncio.run(main.translate_cue({"text": "ドナルド", "language": "ja",
                                             "glossary": "ja|ドナルド = 唐老鸭"}, "test-token"))
    assert result == {"translation": "唐老鸭"}
    assert received == [("ドナルド", "ja", "ja|ドナルド = 唐老鸭", "zh")]
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.translate_cue({"text": "Hello", "language": "en",
                                        "glossary": "invalid"}, "test-token"))
    assert error.value.status_code == 400


def test_translate_cue_respects_target_language(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "settings", DummySettings())
    received = []
    monkeypatch.setattr(main.models, "translate", lambda text, language, glossary, target, context, enabled:
                        received.append((language, target)) or "Hello")
    result = asyncio.run(main.translate_cue({"text": "こんにちは", "language": "ja",
                                             "target_language": "en"}, "test-token"))
    assert result == {"translation": "Hello"}
    assert received == [("ja", "en")]
    assert asyncio.run(main.translate_cue({"text": "Hello", "language": "en",
                                           "target_language": "en"}, "test-token")) == {"translation": "Hello"}
    assert received == [("ja", "en")]
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.translate_cue({"text": "Hola", "language": "es",
                                        "target_language": "xx"}, "test-token"))
    assert error.value.status_code == 400


def test_diagnostics_requires_token_and_contains_only_timings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "settings", DummySettings())
    monkeypatch.setattr(main, "active_session", None)
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.diagnostics(None))
    assert error.value.status_code == 401
    assert asyncio.run(main.diagnostics("test-token")) == {
        "samples": 0, "latest": None, "average_ms": None}


def test_http_translate_cue_accepts_boolean_term_pack_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "settings", DummySettings())
    received = []
    monkeypatch.setattr(main.models, "translate", lambda text, language, glossary, target, context, enabled:
                        received.append(enabled) or "米老鼠")
    body = json.dumps({"text": "Mickey Mouse", "language": "en",
                       "target_language": "zh", "term_pack_enabled": True}).encode()
    sent = []

    async def request() -> None:
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            sent.append(message)

        await main.app({"type": "http", "asgi": {"version": "3.0"}, "method": "POST",
                        "path": "/api/translate-cue", "root_path": "", "query_string": b"",
                        "headers": [(b"x-vat-token", b"test-token"),
                                    (b"content-type", b"application/json")],
                        "scheme": "http", "server": ("127.0.0.1", 8765),
                        "client": ("127.0.0.1", 1000)}, receive, send)

    asyncio.run(request())
    assert sent[0]["status"] == 200
    assert json.loads(sent[1]["body"]) == {"translation": "米老鼠"}
    assert received == [True]
