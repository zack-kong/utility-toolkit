from __future__ import annotations

TRANSLATION_LANGUAGES = {
    "en", "zh", "ja", "ko", "es", "fr", "de", "it", "pt", "ru", "uk",
    "pl", "nl", "tr", "ar", "hi", "id", "vi", "th", "he", "cs", "fa",
    "ms", "bn", "ta", "ur", "te", "mr", "my", "kk",
}

TARGET_LANGUAGES = {
    "zh": "Simplified Chinese", "en": "English", "ja": "Japanese", "ko": "Korean", "es": "Spanish",
}


def translation_source_for(whisper_language: str) -> str | None:
    return whisper_language if whisper_language in TRANSLATION_LANGUAGES else None
