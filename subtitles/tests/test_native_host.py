import io
import json
import struct
import urllib.error

import pytest

from native_host import host


def test_native_message_framing() -> None:
    stream = io.BytesIO()
    host.write_message(stream, {"command": "ensure_running"})
    stream.seek(0)
    assert host.read_message(stream) == {"command": "ensure_running"}
    with pytest.raises(ValueError, match="invalid native message length"):
        host.read_message(io.BytesIO(struct.pack("<I", host.MAX_MESSAGE_BYTES + 1)))


def test_rejects_unregistered_extension_before_launch(tmp_path, monkeypatch) -> None:
    extension_id = "a" * 32
    config_path = tmp_path / "host-config.json"
    config_path.write_text(json.dumps({"project_root": str(tmp_path), "extension_id": extension_id}))
    monkeypatch.setattr(host, "ensure_running", lambda root: pytest.fail("service must not start"))
    with pytest.raises(PermissionError, match="not allowed"):
        host.handle({"command": "ensure_running"}, "chrome-extension://" + "b" * 32, config_path)
    with pytest.raises(ValueError, match="unsupported native command"):
        host.handle({"command": "delete_files"}, "chrome-extension://" + extension_id + "/", config_path)


def test_token_is_stable(tmp_path) -> None:
    first = host.get_token(tmp_path)
    assert first == host.get_token(tmp_path)
    assert len(first) >= 32


def test_unreachable_local_service_is_not_fatal(monkeypatch) -> None:
    class Unreachable:
        def open(self, request, timeout):
            raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(host.urllib.request, "build_opener", lambda *args: Unreachable())
    assert host.service_healthy("test-token") is False
