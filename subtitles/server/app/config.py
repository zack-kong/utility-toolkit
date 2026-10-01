from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def app_data_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    return Path(root or Path.home()) / "VideoAutoTranslate"


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_dir: Path
    token_file: Path
    models_dir: Path

    @classmethod
    def load(cls) -> "Settings":
        data_dir = Path(os.environ.get("VAT_DATA_DIR", app_data_dir()))
        return cls(
            host="127.0.0.1",
            port=int(os.environ.get("VAT_PORT", "8765")),
            data_dir=data_dir,
            token_file=data_dir / "token.txt",
            models_dir=data_dir / "models",
        )

    def token(self) -> str:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.token_file.exists():
            return self.token_file.read_text(encoding="utf-8").strip()
        token = secrets.token_urlsafe(32)
        self.token_file.write_text(token + "\n", encoding="utf-8")
        return token
