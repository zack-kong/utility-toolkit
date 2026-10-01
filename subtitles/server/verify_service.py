"""Stream a local speech sample through the running WebSocket service."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
from faster_whisper.audio import decode_audio
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedOK

from server.app.config import Settings
from server.app.protocol import encode_audio_packet


async def verify(audio_path: Path) -> None:
    settings = Settings.load()
    audio = decode_audio(str(audio_path))
    if audio.size == 0:
        raise ValueError("verification audio is empty")
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    events: list[dict[str, object]] = []
    uri = f"ws://{settings.host}:{settings.port}/ws"
    async with connect(
        uri, origin="chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        subprotocols=["vat", f"token.{settings.token()}"], proxy=None,
    ) as socket:
        await socket.send(json.dumps({
            "type": "start", "session_id": "verification", "epoch": 0,
            "mode": "accurate", "audio_mode": "dialogue",
        }))
        ready = json.loads(await asyncio.wait_for(socket.recv(), timeout=90))
        if ready.get("type") != "status" or ready.get("state") != "ready":
            raise RuntimeError(f"service did not become ready: {ready}")
        print("service_ready=true", flush=True)
        started = time.perf_counter()
        chunk_samples = 4000
        for sequence, offset in enumerate(range(0, pcm.size, chunk_samples)):
            chunk = pcm[offset:offset + chunk_samples]
            await socket.send(encode_audio_packet(0, sequence, chunk.tobytes()))
            await asyncio.sleep(chunk.size / 16000)
        await socket.send(json.dumps({"type": "stop"}))
        try:
            while True:
                raw = await asyncio.wait_for(socket.recv(), timeout=90)
                event = json.loads(raw)
                events.append(event)
                if event.get("type") == "subtitle":
                    print(f"subtitle_final={event.get('final')}", flush=True)
                elif event.get("type") == "error":
                    raise RuntimeError(f"service inference failed: {event}")
        except ConnectionClosedOK:
            pass
        print(f"stream_seconds={time.perf_counter() - started:.2f}", flush=True)
    finals = [event for event in events if event.get("type") == "subtitle" and event.get("final")]
    if not finals or not any(re.search(r"[\u4e00-\u9fff]", str(event.get("translation", ""))) for event in finals):
        raise RuntimeError("service produced no final bilingual subtitle")
    print(f"final_subtitle_count={len(finals)}", flush=True)
    print("verification=passed", flush=True)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    args = parser.parse_args()
    asyncio.run(verify(args.audio))


if __name__ == "__main__":
    main()
