# Privacy and local data

The extension captures only the active tab after you start it. Audio is streamed to the service on `127.0.0.1:8765`; when the page exposes an enabled HTML5 caption track, its text is sent to that same local service instead. The service uses a locally generated token and rejects unauthenticated requests. No cloud translation or speech-recognition API is used during captioning.

The first model download connects to the upstream model and runtime providers named in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Those providers receive a normal download request; they do not receive the video's audio or captions through this app.

The extension stores settings, a custom glossary, and the local service token in Chrome extension storage. The native helper also stores the token and downloaded artifacts in `.local-data/` under the project by default. The optional manual service can use `%LOCALAPPDATA%\VideoAutoTranslate` if `VAT_DATA_DIR` is unset. Keep the token private and do not publish either data directory.

Caption history exists only in the current page's memory (at most 100 final captions). It is cleared when captions close, playback ends, or the video seeks. The service keeps recent numeric processing timings in memory for diagnostics. The application does not intentionally persist raw audio or recognized text, and the repository ignores local logs, model caches, build outputs, and the token directory. Browser and operating-system behavior are outside this project's control.

To remove project-local data, first stop the service and unregister the native helper, then delete the local `.local-data/` directory yourself. This also removes downloaded models and the token. The project does not delete user data automatically.
