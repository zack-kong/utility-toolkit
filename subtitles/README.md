# Local Bilingual Subtitles

A Windows-first Chrome 116+ extension that creates bilingual captions for the active HTML5 video tab. If the page exposes an enabled HTML5 caption track, the extension translates that text locally. Otherwise it captures tab audio and performs local speech recognition, voice activity detection, and translation. Audio and recognized text are sent only to the loopback service at `127.0.0.1`; the first model download contacts the providers listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

This is a development prototype, not a Chrome Web Store release. It supports one active tab at a time. Captions appear **after** speech, not in perfect sync. It cannot obtain future decoded speech from an ordinary browser video buffer. DRM, sandboxed frames, unsupported players, and direct `<video>` fullscreen can prevent capture or hide the overlay. Overlapping speakers, music, and fast or stylized speech can be missed or mistranslated. No accuracy or latency guarantee is made.

## Features

- Source language: auto-detect, English, Japanese, Korean, or Spanish. Target language: Simplified Chinese, English, Japanese, Korean, or Spanish. Defaults to auto-detect → Simplified Chinese.
- Speed-first mode shows replaceable drafts; accuracy-first mode waits for speech segmentation. Neither predicts words that have not been spoken.
- Translation may use up to six confirmed prior source/translation pairs (at most 240 characters) to infer the current topic and resolve ambiguity. Speech recognition uses up to three confirmed same-language source captions (at most 160 characters). Drafts are excluded. Seeking or changing languages clears this context.
- The overlay can be dragged and resized. It shows one to three recent captions, keeps up to 100 final captions in an in-memory history panel, and has a **Close captions** button. Opening history pauses the current HTML5 video; closing it does not resume playback automatically.
- Four small bundled, opt-out term packs cover selected full character names in English, Japanese, Korean, and Spanish when translating to Simplified Chinese. Each currently has four entries. Custom glossary entries take priority. These are starter packs, not a general dictionary.
- No raw audio or recognized text is intentionally logged or written to disk. The authenticated `/api/diagnostics` endpoint retains only recent numeric queue, recognition, and translation timings in memory. See [PRIVACY.md](PRIVACY.md).

## Requirements

- Windows, Chrome 116+, Conda, and an NVIDIA CUDA GPU. A 12 GB GPU is recommended; available GPU memory is checked before model startup. This version has no CPU fallback.
- About 5 GB of free disk space for the models and inference runtime. Downloading requires an explicit click in extension settings.
- Python 3.11 and Node.js for the JavaScript tests.

## Install and run

Run these commands from this `subtitles` directory in PowerShell:

```powershell
conda env create --prefix .\.conda -f environment.yml
```

Open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select the `extension` directory. Copy the extension ID shown by Chrome. To enable one-click service startup from the extension icon, register the native helper with your own ID:

```powershell
.\.conda\python.exe -m pip install -r native_host\requirements-build.txt
.\native_host\install.ps1 -ExtensionId '<your-32-character-extension-id>'
```

Reload the extension and refresh any video tabs that were already open. Click the icon on a video tab to start or stop captions. The first click starts the registered local service at `127.0.0.1:8765`; open the extension settings and click **Download models** before the first translation. The service stays running after captions stop for faster reuse. The native host registration is per-user; moving the directory or changing the extension ID requires rerunning `install.ps1`. Run `native_host\unregister.ps1` to remove the registration without deleting models.

For manual service startup, use the same project-local data directory in every terminal:

```powershell
$env:VAT_DATA_DIR = Join-Path (Get-Location) '.local-data'
.\.conda\python.exe -m server.app.main --print-token
.\.conda\python.exe -m server.app.main
```

Paste the printed token into the extension settings only when using manual startup. Keep it private. Without `VAT_DATA_DIR`, the service uses `%LOCALAPPDATA%\VideoAutoTranslate`.

## Tests

```powershell
.\.conda\python.exe -m pytest -q
node --test tests/test_extension.cjs
```

These tests do not download models or benchmark accuracy. With models already downloaded, `python -m server.verify_models --audio 'path\to\speech.wav'` checks local model loading, and `python -m server.verify_service 'path\to\speech.wav'` checks the WebSocket audio path. Use the same `VAT_DATA_DIR` for both. Performance and content quality must be measured on representative videos; no benchmark figures are claimed here.

## Responsible use and licenses

This repository contains source code and small term files, not model weights, CUDA libraries, or `llama-server.exe`. The project code is licensed under [MIT](../LICENSE). Downloaded models, runtimes, and dependencies retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Respect video copyright, website terms, privacy, and any applicable rules before capturing or translating content. Do not use the extension to bypass DRM or access controls.

Security concerns: see [SECURITY.md](../SECURITY.md). Contributions: see [CONTRIBUTING.md](../CONTRIBUTING.md).
