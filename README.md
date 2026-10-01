# Utility Toolkit

A collection of small, local-first utilities. The first tool, **Local Bilingual Subtitles**, adds bilingual captions to videos playing in Chrome. It prefers a site's available HTML5 captions and otherwise processes captured tab audio with speech recognition and translation models running on your Windows PC. During captioning, audio and text stay on the local machine; model downloads require an internet connection.

This is source code for a development prototype, not a hosted service or a Chrome Web Store package. Each tool has its own requirements and setup instructions.

## Tools

| Tool | Description | Platform |
| --- | --- | --- |
| [Subtitles](subtitles/README.md) | Local bilingual captions for the active Chrome video tab | Windows, Chrome 116+, NVIDIA CUDA |

Start with the [Subtitles project overview](subtitles/README.md), then follow its [Windows installation and local deployment guide](subtitles/DEPLOYMENT.md). The tool also has [privacy](subtitles/PRIVACY.md) and [third-party](subtitles/THIRD_PARTY_NOTICES.md) notices. Model weights and native runtime binaries are downloaded separately and are not part of this repository.

## License and contribution

Original project code is available under the [MIT License](LICENSE). Third-party components retain their own terms; review [the subtitles notices](subtitles/THIRD_PARTY_NOTICES.md) before redistributing a bundle. Contributions are welcome under [CONTRIBUTING.md](CONTRIBUTING.md). Security guidance is in [SECURITY.md](SECURITY.md).
