"""Small, opt-out, offline terminology starter packs with Wikidata provenance."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SUPPORTED_PACKS = frozenset({"en", "ja", "ko", "es"})


@lru_cache(maxsize=4)
def terms_for(language: str) -> tuple[tuple[str, str], ...]:
    if language not in SUPPORTED_PACKS:
        return ()
    path = Path(__file__).with_name("term_packs") / f"{language}.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    return tuple((row["source"], row["target"]) for row in rows)
