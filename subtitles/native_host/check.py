"""Exercise the built native host without printing the local service token."""

from __future__ import annotations

import json
import struct
import subprocess
import urllib.request
from pathlib import Path


def main() -> None:
    dist = Path(__file__).resolve().parent / "dist"
    config = json.loads((dist / "host-config.json").read_text(encoding="utf-8-sig"))
    payload = json.dumps({"command": "ensure_running"}).encode("utf-8")
    process = subprocess.run(
        [str(dist / "vat-native-host.exe"), f"chrome-extension://{config['extension_id']}/"],
        input=struct.pack("<I", len(payload)) + payload,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(dist), timeout=35,
    )
    if process.returncode != 0 or len(process.stdout) < 4:
        raise RuntimeError(f"native host process failed: {process.stderr.decode('utf-8', errors='replace')}")
    response_length = struct.unpack("<I", process.stdout[:4])[0]
    response = json.loads(process.stdout[4:4 + response_length])
    if len(process.stdout) != 4 + response_length or not response.get("ok") or not response.get("token"):
        raise RuntimeError(f"native host did not start the service: {response.get('error', 'invalid response')}")
    print(f"native_host_state={response['state']}")
    request = urllib.request.Request(
        "http://127.0.0.1:8765/health", headers={"X-Vat-Token": response["token"]},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=3) as health_response:
        health = json.load(health_response)
    if health.get("service") != "video-auto-translate":
        raise RuntimeError("native host started an unexpected service")
    print(f"model_downloaded={health['downloaded']}")
    print("verification=passed")


if __name__ == "__main__":
    main()
