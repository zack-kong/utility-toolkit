"""Smoke-test locally downloaded models without starting the browser service."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

from server.app.config import Settings
from server.app.models import ModelRegistry


def gpu_memory() -> str:
    return subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"],
        text=True,
        timeout=5,
    ).strip()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, help="optional speech sample decoded by PyAV")
    args = parser.parse_args()
    settings = Settings.load()
    registry = ModelRegistry(settings.models_dir, token=settings.token())
    if not registry.status()["downloaded"]:
        raise RuntimeError("model files are incomplete")
    print(f"gpu_before_used_free_mb={gpu_memory()}", flush=True)
    started = time.perf_counter()
    registry.load()
    print(f"load_seconds={time.perf_counter() - started:.2f}", flush=True)
    print(f"gpu_after_load_used_free_mb={gpu_memory()}", flush=True)
    started = time.perf_counter()
    translation = registry.translate("Hello, this is a test of local video subtitles.", "en")
    print(f"translation_seconds={time.perf_counter() - started:.2f}", flush=True)
    has_chinese = bool(re.search(r"[\u4e00-\u9fff]", translation))
    print(f"translation_has_chinese={has_chinese}", flush=True)
    if not has_chinese:
        raise RuntimeError("translation did not contain Chinese characters")
    if args.audio:
        from faster_whisper.audio import decode_audio

        audio = decode_audio(str(args.audio))
        started = time.perf_counter()
        result = registry.transcribe(audio, "accurate", None)
        print(f"transcription_seconds={time.perf_counter() - started:.2f}", flush=True)
        print(f"transcription_language={result.language}", flush=True)
        print(f"transcription_nonempty={bool(result.text)}", flush=True)
        if not result.text:
            raise RuntimeError("speech sample produced no transcript")
    print(f"gpu_after_inference_used_free_mb={gpu_memory()}", flush=True)
    print("verification=passed", flush=True)


if __name__ == "__main__":
    main()
