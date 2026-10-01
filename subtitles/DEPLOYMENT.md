# Windows installation and local deployment

This guide runs the Chrome extension and Python service **on the same Windows PC**. The service listens only on `127.0.0.1:8765`; this project does not provide a cloud/server deployment or a Chrome Web Store package. Run PowerShell commands from the `subtitles/` directory unless a step says otherwise. Do not upload `.local-data/`, logs, tokens, model files, or captured media.

## 1. Check prerequisites

- Windows with Chrome 116 or newer.
- An NVIDIA CUDA-capable GPU. A 12 GB GPU is recommended; the service checks free VRAM when loading models. There is no CPU fallback in this version.
- Conda, Git, and enough disk space for a project environment plus approximately 5 GB of model/runtime downloads. Node.js is only needed for the JavaScript tests.
- Internet access for Conda/Python dependencies and the initial model download. Caption processing itself uses the local service.

## 2. Get the source and create the environment

In PowerShell, choose a directory where you want to keep the checkout, then run:

```powershell
git clone https://github.com/zack-kong/utility-toolkit.git
Set-Location .\utility-toolkit\subtitles
conda env create --prefix .\.conda -f environment.yml
.\.conda\python.exe -m pip install -r native_host\requirements-build.txt
```

Do not move the checkout after registering the helper without repeating the registration step. The environment is installed under this project's `.conda/`, not globally.

## 3. Load the Chrome extension

1. Open `chrome://extensions` in Chrome and enable **Developer mode**.
2. Click **Load unpacked** and select this checkout's `subtitles\extension` directory. Do not select the repository root.
3. Copy the extension ID shown on its card. It is 32 characters long; the installer validates it.
4. Back in PowerShell, register the per-user native helper, replacing the placeholder with that ID:

```powershell
.\native_host\install.ps1 -ExtensionId '<your-32-character-extension-id>'
```

The installer builds `native_host\dist\vat-native-host.exe`, writes a local host manifest, and registers it under the current Windows user's Chrome Native Messaging registry key. It does not install a system-wide service. Reload the extension in `chrome://extensions`, then refresh any video tabs that were already open.

If another checkout of this project already owns the same native host registration, the installer refuses to overwrite it. Use `native_host\unregister.ps1` **from the previously registered checkout** first, or keep using that checkout. Do not delete or overwrite its registry entry blindly.

## 4. Start the service and download models

1. Open a supported video page and click the extension icon once. The native helper starts the Python service and supplies its local token to the extension. If models are not installed yet, captions will not work until the next step; the service can remain running.
2. Open the extension's **Options** page. Click **Check service**; a successful response shows the local service status.
3. Click **Download models** and confirm the download. This retrieves faster-whisper medium, Hy-MT2 1.8B GGUF, and the llama.cpp CUDA runtime. Wait until **Check service** reports `downloaded: true` and `download_state: "ready"`. The first load can take additional time and VRAM.
4. On a video tab, click the extension icon to start captions (or stop an existing session). Select source/target languages and mode in Options. The default target language is Simplified Chinese. The in-video caption bar can change languages during playback.

The native helper keeps the service running after captions stop so that models can be reused. Its project-local token and downloads live in `.local-data/`; service logs live in `logs/`. Both directories are ignored by Git. See [privacy details](PRIVACY.md) and [third-party licenses](THIRD_PARTY_NOTICES.md).

## Manual service startup (without the native helper)

Use this if you do not want native-helper registration. From `subtitles/` in PowerShell:

```powershell
$env:VAT_DATA_DIR = Join-Path (Get-Location) '.local-data'
.\.conda\python.exe -m server.app.main --print-token
.\.conda\python.exe -m server.app.main
```

The first command prints a secret token and exits; keep it private. The second command occupies the terminal while the service runs. Paste the token into **Local service token** in extension Options, click **Save settings**, then **Check service**. Keep `VAT_DATA_DIR` pointing to the same location on every manual start. Without it, the service defaults to `%LOCALAPPDATA%\VideoAutoTranslate`. Clicking the extension icon should reuse a healthy manually started service when the saved token matches.

## Verify the installation

For an automated check that does **not** download models, run from `subtitles/`:

```powershell
.\.conda\python.exe -m pytest -q
node --test tests/test_extension.cjs
```

Node.js is needed for the second command. After native-helper registration, `native_host\check.py` tests that the helper can start or reach the service without printing the token:

```powershell
.\.conda\python.exe native_host\check.py
```

These checks do not measure transcription or translation quality. For a real video check, start captions on a supported HTML5 video with speech. You should still hear the original audio, and captions should appear after a processing delay. If the site exposes an enabled HTML5 text track, the extension uses it first; otherwise it captures tab audio.

## Update or move the checkout

Stop captions before updating. From `subtitles/`, run `git -C .. pull --ff-only`, then update the environment if `environment.yml` or requirements changed. Reload the unpacked extension and refresh video tabs. If the directory moved or Chrome assigned a new extension ID, unregister the old checkout's helper and run `install.ps1` again with the current ID. A newly cloned checkout has a different `.local-data/` directory unless you intentionally transfer local data; never put tokens or models into Git.

To remove the registration, run `native_host\unregister.ps1` from the checkout that owns it. This does not stop an already running Python service or delete its models. Remove local data only after you are sure you no longer need it.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Extension cannot start the service | Confirm the extension ID, reload the extension, run `native_host\check.py`, and inspect the newest file in `logs/`. A moved checkout needs re-registration. |
| **Check service** cannot connect | Confirm the service is running on `127.0.0.1:8765` and that the token in Options matches the service. Do not expose this port to the network. |
| Models are unavailable | Complete **Download models**, then check `download_state` and `download_error` via **Check service**. Check free disk space and internet access. |
| GPU or DLL error | Confirm an NVIDIA CUDA GPU and driver, free VRAM, and the CUDA packages in the project Conda environment. This version has no CPU fallback. |
| No captions or a stale overlay | Refresh the video tab after reloading the extension. Try a normal HTML5 video; DRM, sandboxed frames, unsupported players, and some fullscreen modes are not supported. |
| Audio stops after starting | Stop captions and reload the extension. Tab audio must be routed back to the speakers by the offscreen document; file an issue with non-sensitive reproduction steps if this repeats. |

Do not post a local token, raw audio, transcripts, or logs containing private data in a public issue. See the [security guidance](../SECURITY.md).
