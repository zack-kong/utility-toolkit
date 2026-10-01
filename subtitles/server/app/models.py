from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .hy_translate import HyTranslator
from .languages import TARGET_LANGUAGES, translation_source_for
from .term_packs import terms_for

WHISPER_REPOSITORY = "Systran/faster-whisper-medium"
HY_REPOSITORY = "tencent/Hy-MT2-1.8B-GGUF"
HY_REVISION = "a0c709d9fac510f2c807aa3af52872340dc37a4a"
HY_FILENAME = "Hy-MT2-1.8B-Q8_0.gguf"
HY_SHA256 = "5c3fe0b1408a5ceb0143184ef247b11b579c525f4b02b060e6c851bb76fef1a4"
LLAMA_RELEASE = "b11146"
LLAMA_ARCHIVES = {
    "llama-b11146-bin-win-cuda-12.4-x64.zip":
        "3c806a6ceccc3dae1c743ceb1a1fb2cce5b76f40bfbd4c6b7b8afb6ef45a5807",
    "cudart-llama-bin-win-cuda-12.4-x64.zip":
        "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
}
_dll_handles: list[object] = []


def prepare_cuda_dlls() -> None:
    if sys.platform != "win32" or _dll_handles:
        return
    site_packages = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    directories = [site_packages / name / "bin" for name in ("cuda_runtime", "cuda_nvrtc", "cublas", "cudnn")]
    missing = [str(directory) for directory in directories if not directory.is_dir()]
    if missing:
        raise ModelNotReady("CUDA 12 libraries are missing from this project environment. Reinstall server/requirements.txt.")
    for directory in directories:
        _dll_handles.append(os.add_dll_directory(str(directory)))
    os.environ["PATH"] = os.pathsep.join(map(str, directories)) + os.pathsep + os.environ["PATH"]


class ModelNotReady(RuntimeError):
    pass


@dataclass
class Transcript:
    text: str
    language: str
    language_probability: float


class ModelRegistry:
    """Explicit model download and lazy GPU loading.

    Importing this module does not import CUDA runtimes, so the health endpoint
    remains useful on machines where models are not yet installed.
    """

    def __init__(self, models_dir: Path, token: str = ""):
        self.models_dir = models_dir
        self.whisper_dir = models_dir / "faster-whisper-medium"
        self.hy_dir = models_dir / "hy-mt2-1.8b"
        self.hy_file = self.hy_dir / HY_FILENAME
        self.runtime_dir = models_dir.parent / "runtime" / f"llama-{LLAMA_RELEASE}"
        self.llama_server = self.runtime_dir / "bin" / "llama-server.exe"
        self._whisper = None
        self._translator = HyTranslator(self.hy_file, self.llama_server, token)
        self._translation_loaded = False
        self._download_lock = asyncio.Lock()
        self._load_lock = threading.Lock()
        self._translate_lock = threading.Lock()
        self.download_state = "not_downloaded"
        self.download_error: str | None = None

    def status(self) -> dict[str, object]:
        downloaded = ((self.whisper_dir / "model.bin").is_file()
                      and self.hy_file.is_file() and self.llama_server.is_file())
        return {
            "downloaded": downloaded,
            "loaded": self._whisper is not None and self._translation_loaded,
            "translation_loaded": self._translation_loaded,
            "download_state": ("ready" if downloaded and self.download_state == "not_downloaded"
                               else self.download_state),
            "download_error": self.download_error,
            "models_dir": str(self.models_dir),
            "whisper": str(self.whisper_dir),
            "translation": str(self.hy_file),
            "translation_model": HY_REPOSITORY,
        }

    async def download(self) -> None:
        async with self._download_lock:
            self.download_state = "downloading"
            self.download_error = None
            try:
                await asyncio.to_thread(self._download_sync)
                self.download_state = "ready"
            except Exception as error:
                self.download_state = "failed"
                self.download_error = str(error)

    def _download_sync(self) -> None:
        from huggingface_hub import snapshot_download

        self.models_dir.mkdir(parents=True, exist_ok=True)
        if not (self.whisper_dir / "model.bin").is_file():
            snapshot_download(WHISPER_REPOSITORY, local_dir=str(self.whisper_dir))
        self._download_file(
            f"https://huggingface.co/{HY_REPOSITORY}/resolve/{HY_REVISION}/{HY_FILENAME}",
            self.hy_file, HY_SHA256,
        )
        for filename, digest in LLAMA_ARCHIVES.items():
            archive = self.runtime_dir / filename
            self._download_file(
                f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_RELEASE}/{filename}",
                archive, digest,
            )
            with zipfile.ZipFile(archive) as bundle:
                root = (self.runtime_dir / "bin").resolve()
                for item in bundle.infolist():
                    if not (root / item.filename).resolve().is_relative_to(root):
                        raise ModelNotReady("The inference runtime archive contains an unsafe path.")
                bundle.extractall(root)
        if not self.llama_server.is_file():
            raise ModelNotReady("The llama.cpp download is missing llama-server.exe.")

    @staticmethod
    def _download_file(url: str, target: Path, expected_sha256: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and ModelRegistry._sha256(target) == expected_sha256:
            return
        partial = target.with_name(target.name + ".part")
        result = subprocess.run(
            ["curl.exe", "--location", "--fail", "--silent", "--show-error", "--retry", "3",
             "--continue-at", "-", "--output", str(partial), url],
            capture_output=True, text=True, timeout=3600,
        )
        if result.returncode or not partial.is_file() or ModelRegistry._sha256(partial) != expected_sha256:
            raise ModelNotReady(f"Download or checksum verification failed: {target.name}. {result.stderr.strip()[:200]}")
        partial.replace(target)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def load(self) -> None:
        if not self.status()["downloaded"]:
            raise ModelNotReady("Models are not downloaded. Click Download models in the extension settings.")
        with self._load_lock:
            if self._whisper is None:
                prepare_cuda_dlls()
                from faster_whisper import WhisperModel

                self._assert_cuda_capacity(4000)
                self._whisper = WhisperModel(
                    str(self.whisper_dir), device="cuda", compute_type="int8_float16",
                    local_files_only=True,
                )
        self.load_translation()

    def load_translation(self) -> None:
        if not self.hy_file.is_file() or not self.llama_server.is_file():
            raise ModelNotReady("The translation model is not downloaded. Click Download models in the extension settings.")
        with self._load_lock:
            if not self._translation_loaded:
                if not self._translator._ready():
                    self._assert_cuda_capacity(3000)
                self._translator.ensure_ready()
                self._translation_loaded = True

    @staticmethod
    def _assert_cuda_capacity(min_free_mb: int) -> None:
        """Require a meaningful margin before allocating both resident models."""
        try:
            output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                text=True, stderr=subprocess.STDOUT, timeout=5,
            )
            free_mb = max(int(line.strip()) for line in output.splitlines() if line.strip())
        except (FileNotFoundError, subprocess.SubprocessError, ValueError) as error:
            raise ModelNotReady("No usable NVIDIA CUDA GPU was found. This development version has no CPU fallback.") from error
        if free_mb < min_free_mb:
            raise ModelNotReady(f"Only {free_mb} MB of GPU memory is free; at least {min_free_mb} MB is required for this step.")

    def transcribe(self, audio: np.ndarray, mode: str, language_hint: str | None,
                   context: str = "", hotwords: str = "") -> Transcript:
        self.load()
        assert self._whisper is not None
        if audio.size == 0:
            raise ValueError("empty audio must not be transcribed")
        beam_size = 1 if mode == "fast" else 5
        segments, info = self._whisper.transcribe(
            audio,
            language=language_hint,
            beam_size=beam_size,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
            initial_prompt=context or None,
            hotwords=hotwords or None,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return Transcript(text, info.language, float(info.language_probability))

    def translate(self, text: str, whisper_language: str, glossary: str = "",
                  target_language: str = "zh", context: str = "",
                  term_pack_enabled: bool = True) -> str:
        if translation_source_for(whisper_language) is None:
            raise ValueError(f"unsupported source language: {whisper_language}")
        if target_language not in TARGET_LANGUAGES:
            raise ValueError(f"unsupported target language: {target_language}")
        self.load_translation()
        with self._translate_lock:
            preset = terms_for(whisper_language) if term_pack_enabled and target_language == "zh" else ()
            return self._translator.translate(text, whisper_language, glossary, target_language, context, preset)
