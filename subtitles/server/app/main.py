from __future__ import annotations

import argparse
import asyncio
import json
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketDisconnected
import uvicorn

from .config import Settings
from .glossary import MAX_GLOSSARY_CHARS, parse_glossary
from .languages import TARGET_LANGUAGES, translation_source_for
from .models import ModelRegistry
from .protocol import decode_audio_packet
from .session import SubtitleSession

settings = Settings.load()
models = ModelRegistry(settings.models_dir)
download_task: asyncio.Task[None] | None = None
active_session_lock = asyncio.Lock()
active_session: SubtitleSession | None = None


def require_token(token: str | None) -> None:
    if token != settings.token():
        raise HTTPException(status_code=401, detail="invalid local service token")


@asynccontextmanager
async def lifespan(_: FastAPI):
    models._translator.token = settings.token()  # Generate before the first extension connection.
    yield


app = FastAPI(title="Video Auto Translate", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/health")
async def health(x_vat_token: str | None = Header(default=None)) -> dict[str, object]:
    require_token(x_vat_token)
    return {"service": "video-auto-translate", "host": settings.host, **models.status()}


@app.get("/api/diagnostics")
async def diagnostics(x_vat_token: str | None = Header(default=None)) -> dict[str, object]:
    require_token(x_vat_token)
    return active_session.diagnostics() if active_session is not None else {
        "samples": 0, "latest": None, "average_ms": None}


@app.post("/api/models/download", status_code=202)
async def download_models(x_vat_token: str | None = Header(default=None)) -> JSONResponse:
    global download_task
    require_token(x_vat_token)
    if download_task is None or download_task.done():
        download_task = asyncio.create_task(models.download())
    return JSONResponse({"status": "downloading", **models.status()}, status_code=202)


@app.post("/api/translate-cue")
async def translate_cue(payload: dict[str, object], x_vat_token: str | None = Header(default=None)) -> dict[str, str]:
    require_token(x_vat_token)
    text_value = payload.get("text", "")
    language_value = payload.get("language", "")
    glossary = payload.get("glossary", "")
    target_language = payload.get("target_language", "zh")
    term_pack_value = payload.get("term_pack_enabled", True)
    if (not isinstance(text_value, str) or not isinstance(language_value, str)
            or not isinstance(glossary, str) or not isinstance(target_language, str)
            or not isinstance(term_pack_value, bool)):
        raise HTTPException(status_code=400, detail="invalid subtitle text or language")
    original = text_value.strip()
    language = language_value.split("-", 1)[0].lower()
    term_pack_enabled = term_pack_value
    if (not original or len(original) > 1000 or translation_source_for(language) is None
            or target_language not in TARGET_LANGUAGES or len(glossary) > MAX_GLOSSARY_CHARS):
        raise HTTPException(status_code=400, detail="invalid subtitle text or language")
    try:
        parse_glossary(glossary)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    translated = (original if language == target_language else
                  await asyncio.to_thread(models.translate, original, language, glossary,
                                          target_language, "", term_pack_enabled))
    return {"translation": translated}


@app.websocket("/ws")
async def subtitles(websocket: WebSocket) -> None:
    global active_session
    origin = websocket.headers.get("origin", "")
    protocols = [part.strip() for part in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    supplied = next((part.removeprefix("token.") for part in protocols if part.startswith("token.")), "")
    if not origin.startswith("chrome-extension://") or "vat" not in protocols or not secrets.compare_digest(supplied, settings.token()):
        await websocket.close(code=1008, reason="invalid local service token")
        return
    if active_session_lock.locked():
        await websocket.close(code=1013, reason="another video session is active")
        return
    await active_session_lock.acquire()
    try:
        await websocket.accept(subprotocol="vat")
    except Exception:
        active_session_lock.release()
        raise
    session: SubtitleSession | None = None

    async def send(event: dict[str, object]) -> None:
        try:
            await websocket.send_text(json.dumps(event, ensure_ascii=False))
        except (WebSocketDisconnect, WebSocketDisconnected):
            # A page may close capture while inference is still finishing.
            return

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("text") is not None:
                data = json.loads(message["text"])
                event_type = data.get("type")
                if event_type == "start":
                    glossary = str(data.get("glossary", ""))
                    try:
                        parse_glossary(glossary)
                    except ValueError as error:
                        await send({"type": "error", "code": "invalid_glossary", "message": str(error)})
                        continue
                    if session is not None:
                        session.close()
                    session = SubtitleSession(
                        session_id=str(data.get("session_id", "unknown")),
                        models=models,
                        send=send,
                        mode="fast" if data.get("mode") == "fast" else "accurate",
                        audio_mode="music" if data.get("audio_mode") == "music" else "dialogue",
                        epoch=int(data.get("epoch", 0)),
                        language_hint=(data.get("source_language") if data.get("source_language") in
                                       {"ja", "en", "ko", "es"} else None),
                        language_locked=data.get("source_language") in {"ja", "en", "ko", "es"},
                        glossary=glossary,
                        target_language=(data.get("target_language") if data.get("target_language") in
                                         TARGET_LANGUAGES else "zh"),
                        term_pack_enabled=data.get("term_pack_enabled", True) is True,
                    )
                    active_session = session
                    try:
                        await asyncio.to_thread(models.load)
                    except Exception as error:
                        await send({"type": "error", "code": "model_unavailable", "message": str(error)})
                        session.close()
                        active_session = None
                        session = None
                        continue
                    await send({"type": "status", "state": "ready", "models": models.status()})
                elif event_type == "reset" and session is not None:
                    session.reset(int(data["epoch"]))
                elif event_type == "configure" and session is not None:
                    target = data.get("target_language")
                    source = data.get("source_language")
                    if target not in TARGET_LANGUAGES or source not in {"auto", "ja", "en", "ko", "es"}:
                        await send({"type": "error", "code": "invalid_protocol", "message": "Unsupported language setting."})
                        continue
                    next_epoch = int(data["epoch"])
                    if next_epoch <= session.epoch:
                        continue
                    session.reset(next_epoch)
                    session.language_hint = None if source == "auto" else source
                    session.language_locked = source != "auto"
                    session.language_candidate = None
                    session.language_candidate_count = 0
                    session.target_language = target
                elif event_type == "stop" and session is not None:
                    session.close()
                    await websocket.close(code=1000)
                    break
                continue
            if message.get("bytes") is not None and session is not None:
                packet = decode_audio_packet(message["bytes"])
                await session.accept_audio(packet.epoch, packet.sequence, packet.pcm16)
    except WebSocketDisconnect:
        pass
    except (ValueError, json.JSONDecodeError) as error:
        await send({"type": "error", "code": "invalid_protocol", "message": str(error)})
    finally:
        if session is not None:
            session.close()
            if session.processing_task is not None:
                await session.processing_task
        active_session = None
        active_session_lock.release()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local Video Auto Translate service")
    parser.add_argument("--print-token", action="store_true", help="print the local extension token and exit")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.print_token:
        print(settings.token())
        return
    uvicorn.run("server.app.main:app", host=settings.host, port=settings.port,
                reload=False, access_log=False)


if __name__ == "__main__":
    main()
