"""Local Hy-MT2 translator served by the bundled llama.cpp binary."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .glossary import matching_terms
from .languages import TARGET_LANGUAGES


class HyTranslator:
    def __init__(self, model_file: Path, server_exe: Path, token: str, port: int = 8766):
        self.model_file = model_file
        self.server_exe = server_exe
        self.token = token
        self.port = port
        self._process: subprocess.Popen[bytes] | None = None
        self._start_lock = threading.Lock()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _ready(self) -> bool:
        request = urllib.request.Request(
            f"{self.base_url}/v1/models", headers={"Authorization": f"Bearer {self.token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                models = json.load(response).get("data", [])
            return any(model.get("id") == "video-auto-translate-hy-mt2" for model in models)
        except (OSError, ValueError, urllib.error.HTTPError):
            return False

    def ensure_ready(self) -> None:
        with self._start_lock:
            if self._ready():
                return
            if not self.model_file.is_file() or not self.server_exe.is_file():
                raise RuntimeError("The Hy-MT2 model or local inference runtime is not downloaded.")
            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("The Hy-MT2 inference service is not ready. Check port 8766.")
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self._process = subprocess.Popen(
                [str(self.server_exe), "--model", str(self.model_file),
                 "--alias", "video-auto-translate-hy-mt2", "--host", "127.0.0.1",
                 "--port", str(self.port), "--ctx-size", "1024", "--parallel", "1",
                 "--n-gpu-layers", "99", "--api-key", self.token, "--jinja",
                 "--log-disable", "--no-webui"],
                cwd=str(self.server_exe.parent), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    raise RuntimeError(f"Hy-MT2 inference failed to start (exit code {self._process.returncode}).")
                if self._ready():
                    return
                time.sleep(0.25)
            self._process.terminate()
            raise RuntimeError("Hy-MT2 inference timed out during startup. Check GPU memory and port 8766.")

    def translate(self, text: str, language: str = "", glossary: str = "",
                  target_language: str = "zh", context: str = "",
                  preset: tuple[tuple[str, str], ...] = ()) -> str:
        if target_language not in TARGET_LANGUAGES:
            raise ValueError(f"unsupported target language: {target_language}")
        terms = matching_terms(text, language, glossary, preset) if target_language == "zh" else []
        for source, target in terms:
            if text.strip().casefold() == source.casefold():
                return target
        self.ensure_ready()
        term_hint = "" if not terms else "Use these established names: " + "; ".join(
            f"{source} → {target}" for source, target in terms) + ".\n"
        context_hint = ("The following confirmed dialogue is context only. Use it to infer the current topic"
                        " and resolve ambiguity, but the topic may have changed. Do not invent speech or"
                        " translate or repeat the history:\n"
                        f"{context[-240:]}\n") if context else ""
        prompt = (f"{term_hint}{context_hint}Translate the current text into {TARGET_LANGUAGES[target_language]}."
                  " Output only the translation, with no explanation or earlier dialogue:\n"
                  f"{text}")
        payload = json.dumps({
            "model": "video-auto-translate-hy-mt2",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7, "top_p": 0.6, "top_k": 20,
            "repeat_penalty": 1.05, "max_tokens": 256,
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions", data=payload,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.load(response)
            translation = result["choices"][0]["message"]["content"].strip()
        except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
            raise RuntimeError("Hy-MT2 translation failed; this caption has no translation.") from error
        if not translation:
            raise RuntimeError("Hy-MT2 returned an empty translation.")
        return translation
