"""Small, explicit terminology hints for culturally established names."""

from __future__ import annotations

import re

BUILTIN_TERMS = {
    "en": (("Donald Duck", "唐老鸭"),),
    "ja": (("ドナルド・ダック", "唐老鸭"), ("ドナルドダック", "唐老鸭")),
}
MAX_GLOSSARY_CHARS = 4000
MAX_MATCHED_TERMS = 8


def parse_glossary(raw: str) -> list[tuple[str | None, str, str]]:
    """Parse `source = target` or `ja|source = target` lines from local settings."""
    if len(raw) > MAX_GLOSSARY_CHARS:
        raise ValueError("The glossary cannot exceed 4,000 characters.")
    entries: list[tuple[str | None, str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        source, separator, target = line.partition("=")
        if not separator:
            raise ValueError('Each glossary line must use "source = Chinese translation", optionally prefixed with "ja|".')
        source, target = source.strip(), target.strip()
        language = None
        if "|" in source:
            language, source = (part.strip() for part in source.split("|", 1))
            if language not in {"ja", "en", "ko", "es", "fr", "de", "zh"}:
                raise ValueError(f"Unsupported glossary language: {language}")
        if not source or not target or len(source) > 80 or len(target) > 80:
            raise ValueError("Source and Chinese translation must be nonempty and no longer than 80 characters each.")
        entries.append((language, source, target))
        if len(entries) > 60:
            raise ValueError("The glossary supports at most 60 entries.")
    return entries


def _contains_term(text: str, term: str) -> bool:
    pattern = re.escape(term)
    if term[0].isascii() and term[0].isalnum():
        pattern = r"(?<![A-Za-z0-9])" + pattern
    elif "\u30a0" <= term[0] <= "\u30ff":
        pattern = r"(?<![\u30a0-\u30ff])" + pattern
    if term[-1].isascii() and term[-1].isalnum():
        pattern += r"(?![A-Za-z0-9])"
    elif "\u30a0" <= term[-1] <= "\u30ff":
        pattern += r"(?![\u30a0-\u30ff])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def matching_terms(text: str, language: str, raw: str = "",
                   preset: tuple[tuple[str, str], ...] = ()) -> list[tuple[str, str]]:
    terms = {(source.casefold()): (source, target) for source, target in BUILTIN_TERMS.get(language, ())}
    for source, target in preset:
        terms[source.casefold()] = (source, target)
    for entry_language, source, target in parse_glossary(raw):
        if entry_language is None or entry_language == language:
            terms[source.casefold()] = (source, target)
    matched = [pair for pair in terms.values() if _contains_term(text, pair[0])]
    return sorted(matched, key=lambda pair: len(pair[0]), reverse=True)[:MAX_MATCHED_TERMS]
