"""Multilingual string lookup (§23.4): ``t(key, lang, **vars)`` over config/i18n/<lang>.yaml (EN / HI / KN / TE).

HI, KN and TE are marked "draft translation" until native speakers review them. A missing key falls back to English,
then to the key itself, so a screen never breaks; tests check that every key exists in every language.
"""
from __future__ import annotations

from functools import lru_cache

from vrikka.config import load_yaml

LANGUAGES = {"en": "English", "hi": "हिन्दी", "kn": "ಕನ್ನಡ", "te": "తెలుగు"}


@lru_cache(maxsize=8)
def strings(lang: str) -> dict:
    if lang not in LANGUAGES:
        raise ValueError(f"unsupported language '{lang}'")
    return load_yaml(f"i18n/{lang}")


def t(key: str, lang: str = "en", **vars) -> str:
    s = strings(lang).get(key) or strings("en").get(key) or key
    return str(s).format(**vars) if vars else str(s)


def is_draft(lang: str) -> bool:
    return strings(lang).get("_meta", {}).get("status") == "draft translation"
