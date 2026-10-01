# Contributing

Please keep changes focused, explain user-visible behavior, and include tests for protocol or state transitions. For the subtitles tool, work from `subtitles/` and run:

```powershell
.\.conda\python.exe -m pytest -q
node --test tests/test_extension.cjs
```

Do not commit model weights, downloaded binaries, tokens, logs, captured media, transcripts, or personal data. Do not add a network service or telemetry without documenting and testing the privacy impact. Confirm third-party license compatibility before copying code, model files, or datasets into the repository.

By submitting a contribution, you agree that your original contribution may be distributed under this repository's MIT License. Preserve upstream notices for third-party material.
