# Third-party components and data

This repository does **not** redistribute model weights, `llama-server.exe`, CUDA libraries, or Python wheels. The local setup downloads or installs them separately. Each component remains governed by its own license and terms; the repository's MIT license does not replace them. Check the linked upstream terms before distributing a package that bundles any of these artifacts.

| Component | Role | Upstream license / source |
| --- | --- | --- |
| [Tencent Hy-MT2-1.8B-GGUF](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF) | Local translation model, Q8_0 | Apache-2.0 per its model card |
| [Systran faster-whisper-medium](https://huggingface.co/Systran/faster-whisper-medium) | Local speech recognition weights | MIT per its model card |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Speech-recognition integration | [MIT](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE) |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | Faster Whisper inference runtime | [MIT](https://github.com/OpenNMT/CTranslate2/blob/master/LICENSE) |
| [Silero VAD](https://github.com/snakers4/silero-vad) | Speech activity validation | [MIT](https://github.com/snakers4/silero-vad/blob/master/LICENSE) |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | Local GGUF translation server | [MIT](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE) |
| [Wikidata](https://www.wikidata.org/wiki/Help:Data_access) | Four small built-in character-name term packs | CC0 data; the source `Q` identifiers remain in each JSON file |
| [NVIDIA CUDA runtime, cuBLAS, and cuDNN](https://developer.nvidia.com/cuda-toolkit) | GPU execution, installed into the project environment | NVIDIA's separate software terms; not included in this repository |

Other Python packages listed in `server/requirements.txt` and `native_host/requirements-build.txt` are installed from their respective package sources and retain their own terms. The extension uses Chrome Manifest V3 browser APIs; Chrome itself is not included.

The app provides text/audio processing tools only. Users are responsible for having permission to capture, translate, display, or share the media they watch and for complying with website rules and applicable law. This project does not provide DRM circumvention.
