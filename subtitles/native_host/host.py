"""One-shot Chrome Native Messaging host for starting the local service."""

from __future__ import annotations

import json
import msvcrt
import os
import secrets
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

MAX_MESSAGE_BYTES = 1024 * 1024


def runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def read_exact(stream, count: int) -> bytes:
    result = bytearray()
    while len(result) < count:
        part = stream.read(count - len(result))
        if not part:
            raise ValueError("incomplete native message")
        result.extend(part)
    return bytes(result)


def read_message(stream) -> dict[str, object]:
    length = struct.unpack("<I", read_exact(stream, 4))[0]
    if length == 0 or length > MAX_MESSAGE_BYTES:
        raise ValueError("invalid native message length")
    message = json.loads(read_exact(stream, length).decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("native message must be an object")
    return message


def write_message(stream, message: dict[str, object]) -> None:
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stream.write(struct.pack("<I", len(payload)))
    stream.write(payload)
    stream.flush()


def read_config(path: Path) -> tuple[Path, str]:
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    root = Path(config["project_root"]).resolve()
    extension_id = str(config["extension_id"])
    if not root.is_dir() or len(extension_id) != 32 or any(char not in "abcdefghijklmnop" for char in extension_id):
        raise ValueError("invalid native host configuration")
    return root, extension_id


def get_token(data_dir: Path) -> str:
    data_dir.mkdir(parents=True, exist_ok=True)
    token_file = data_dir / "token.txt"
    if not token_file.exists():
        try:
            with token_file.open("x", encoding="utf-8") as output:
                output.write(secrets.token_urlsafe(32) + "\n")
        except FileExistsError:
            pass
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError("local service token is empty")
    return token


def service_healthy(token: str) -> bool:
    request = urllib.request.Request("http://127.0.0.1:8765/health", headers={"X-Vat-Token": token})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=1) as response:
            if json.load(response).get("service") != "video-auto-translate":
                raise RuntimeError("port 8765 is occupied by an incompatible service")
            return True
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"port 8765 is occupied by an incompatible service (HTTP {error.code})") from error
    except urllib.error.URLError as error:
        if isinstance(error.reason, (ConnectionRefusedError, TimeoutError)):
            return False
        raise RuntimeError(f"local service health check failed: {error.reason}") from error


def launch_service(root: Path, data_dir: Path, token: str) -> int:
    python = root / ".conda" / "python.exe"
    if not python.is_file():
        raise RuntimeError("project Python environment is missing")
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"native-service-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.log"
    environment = os.environ.copy()
    environment["VAT_DATA_DIR"] = str(data_dir)
    environment["PYTHONIOENCODING"] = "utf-8"
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            [str(python), "-u", "-m", "server.app.main"],
            cwd=str(root), env=environment, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"local service exited; inspect {log_path}")
        if service_healthy(token):
            return process.pid
        time.sleep(0.25)
    process.terminate()
    raise RuntimeError(f"local service did not become ready; inspect {log_path}")


def ensure_running(root: Path) -> dict[str, object]:
    data_dir = root / ".local-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / "native-host.lock").open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            token = get_token(data_dir)
            if service_healthy(token):
                return {"ok": True, "state": "running", "token": token}
            pid = launch_service(root, data_dir, token)
            return {"ok": True, "state": "started", "token": token, "pid": pid}
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def handle(message: dict[str, object], origin: str, config_path: Path) -> dict[str, object]:
    root, extension_id = read_config(config_path)
    if origin.rstrip("/") != f"chrome-extension://{extension_id}":
        raise PermissionError("extension origin is not allowed")
    if message.get("command") != "ensure_running":
        raise ValueError("unsupported native command")
    return ensure_running(root)


def main() -> None:
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    try:
        message = read_message(sys.stdin.buffer)
        origin = sys.argv[1] if len(sys.argv) > 1 else ""
        result = handle(message, origin, runtime_dir() / "host-config.json")
    except Exception as error:
        result = {"ok": False, "error": str(error)}
    write_message(sys.stdout.buffer, result)


if __name__ == "__main__":
    main()
