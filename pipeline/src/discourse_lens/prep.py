"""Text cleaning + quality gating utilities applied just-in-time before embedding.

Kept separate from ingest because the cache is the source of truth; cleaning
rules can change without re-pulling the API. Idempotent and pure-text.
"""
from __future__ import annotations
import re
from functools import lru_cache

# Many publishers prefix the body of the abstract with the literal word "Abstract"
# (Springer/Wiley JATS export pattern). Strip when leading.
_ABSTRACT_PREFIX_RE = re.compile(r"^\s*Abstract[:\.\s]+", re.IGNORECASE)

# JATS-style and HTML entities sometimes survive
_HTML_ENTITY_RE = re.compile(r"&[a-z]+;|&#\d+;")
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# OpenAlex inverted-index reconstruction occasionally produces stray "<P>" or
# section headers like "INTRODUCTION:" — light strip
_LEADING_SECTION_RE = re.compile(r"^\s*(?:<P>\s*)?(?:INTRODUCTION|BACKGROUND|PURPOSE)\s*[:.\-]\s*",
                                 re.IGNORECASE)

MIN_WORDS = 30   # below this, abstract is likely stub/placeholder
MAX_WORDS = 800  # above this, likely captured the body, not the abstract


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = _HTML_TAG_RE.sub(" ", text)
    text = _HTML_ENTITY_RE.sub(" ", text)
    text = _ABSTRACT_PREFIX_RE.sub("", text)
    text = _LEADING_SECTION_RE.sub("", text)
    text = " ".join(text.split())
    return text


def quality_gate(text: str) -> tuple[bool, str]:
    """Returns (passes, reason)."""
    if not text:
        return False, "empty"
    n = len(text.split())
    if n < MIN_WORDS:
        return False, f"too_short ({n} words)"
    if n > MAX_WORDS:
        return False, f"too_long ({n} words; likely body)"
    return True, "ok"


@lru_cache(maxsize=1)
def _detector():
    from langdetect import DetectorFactory
    DetectorFactory.seed = 42  # deterministic
    from langdetect import detect
    return detect


def is_english(text: str) -> bool:
    if not text:
        return False
    try:
        return _detector()(text[:1000]) == "en"
    except Exception:
        return True  # fail-open: keep paper if detector chokes


def doc_for_embedding(title: str, abstract: str) -> str:
    """Concatenate title + cleaned abstract for embedding & keyword extraction."""
    t = normalize_text(title)
    a = normalize_text(abstract)
    if t and not t.endswith("."):
        t += "."
    return f"{t} {a}".strip()
