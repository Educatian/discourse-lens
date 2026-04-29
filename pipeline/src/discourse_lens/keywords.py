"""KeyBERT keyphrase extraction per abstract.

Reuses the same MPNet model as embed.py (KeyBERT accepts an embedder).
Extracts top-5 candidate keyphrases (n-gram 1-3) per document with MaxSum
diversity. Aggregated counts feed the per-field keyword network in network.py.
"""
from __future__ import annotations
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

console = Console()

# Strip phrases that are pure stopwords / cluttery
_NOISE_PATTERNS = [
    re.compile(r"^(?:the|a|an|of|to|for|in|on|at|with|by|and|or|study|research|paper|article|present|propose|provide|review|analysis)$", re.I),
    re.compile(r"^[\d\s\-\.]+$"),
    # Reduplicated phrases like "design design" — KeyBERT artifact
    re.compile(r"^(\w+)\s+\1$", re.I),
]
# Generic terms common in any academic abstract — strip
_GENERIC = {
    "study", "research", "paper", "article", "literature", "implications",
    "results", "findings", "method", "methods", "results show", "this paper",
    "this study", "this research", "this article",
    # Journal-name fragments leaking through from titles in the corpus
    "journal", "journal learning", "sciences jls", "sciences", "jls",
    "international journal", "learning teaching",
    # Single fragments that aren't really keyphrases on their own
    "learners", "learning", "students", "teachers", "teaching", "education",
    "design", "designs", "designing",
}


def lemma_collapse_key(phrase: str) -> str:
    """Group phrases that are token-permutations of each other.

    'course design' and 'design course' → both map to 'course design' (sorted).
    'students collaborative' and 'collaborative students' → 'collaborative students'.
    """
    return " ".join(sorted(phrase.split()))

KEYBERT_MODEL = "all-MiniLM-L6-v2"  # CPU-friendly; sm_120 GPU needs torch 2.7+/cu128 not yet installed


def is_noise(phrase: str) -> bool:
    p = phrase.strip().lower()
    if not p or len(p) < 3:
        return True
    if p in _GENERIC:
        return True
    for pat in _NOISE_PATTERNS:
        if pat.match(p):
            return True
    return False


def normalize_phrase(p: str) -> str:
    """Lowercase + collapse whitespace + strip punctuation tails."""
    p = p.lower().strip()
    p = re.sub(r"\s+", " ", p)
    p = p.strip(".,;:!?-_'\"()[]{}")
    return p


def extract_keyphrases(
    rows: Iterable[dict],
    docs: list[str],
    top_n: int = 5,
) -> list[list[str]]:
    """Returns one list of top-n keyphrases per doc, aligned with input order."""
    from keybert import KeyBERT
    from sentence_transformers import SentenceTransformer

    console.print(f"loading KeyBERT with {KEYBERT_MODEL} on CPU...")
    embed_model = SentenceTransformer(KEYBERT_MODEL, device="cpu")
    kw = KeyBERT(model=embed_model)

    out: list[list[str]] = []
    import time as _t
    t0 = _t.monotonic()
    err_seen = False
    for i, doc in enumerate(docs):
        try:
            raw = kw.extract_keywords(
                doc,
                keyphrase_ngram_range=(1, 2),
                stop_words="english",
                use_maxsum=False,                # simpler top-N for CPU speed
                top_n=top_n,
            )
        except Exception as _e:
            if not err_seen:
                print(f"  WARN keyphrase error doc {i}: {type(_e).__name__}: {_e}", flush=True)
                err_seen = True
            raw = []
        phrases = []
        for phrase, _score in raw:
            p = normalize_phrase(phrase)
            if not is_noise(p):
                phrases.append(p)
        out.append(phrases)
        if (i + 1) % 100 == 0 or i + 1 == len(docs):
            elapsed = _t.monotonic() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(docs) - i - 1) / rate if rate > 0 else 0
            print(f"  keyphrase {i+1}/{len(docs)}  ({rate:.1f} docs/s, eta {eta:.0f}s)", flush=True)
    return out


def aggregate_per_field(rows: list[dict], keyphrases_per_doc: list[list[str]]) -> dict:
    """Per-field keyphrase frequency + per-doc keyphrase set.

    Returns {
      "ls": {"freq": Counter, "doc_keyphrases": {doi: [phrases]}},
      "et": {...},
      "all": {"freq": Counter}
    }
    """
    by_field: dict[str, dict] = {
        "LS": {"freq": Counter(), "doc_kp": {}},
        "ET": {"freq": Counter(), "doc_kp": {}},
    }
    all_freq: Counter = Counter()
    for r, kps in zip(rows, keyphrases_per_doc):
        f = r["field"]
        by_field[f]["freq"].update(set(kps))   # per-doc unique
        by_field[f]["doc_kp"][r["doi"]] = kps
        all_freq.update(set(kps))
    return {
        "ls": {"freq": dict(by_field["LS"]["freq"]),
               "doc_keyphrases": by_field["LS"]["doc_kp"]},
        "et": {"freq": dict(by_field["ET"]["freq"]),
               "doc_keyphrases": by_field["ET"]["doc_kp"]},
        "all": {"freq": dict(all_freq)},
    }


def save_keyphrase_table(agg: dict, out_path: str | Path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(agg, indent=2, ensure_ascii=False), encoding="utf-8")
    n_ls = len(agg["ls"]["freq"])
    n_et = len(agg["et"]["freq"])
    n_all = len(agg["all"]["freq"])
    console.print(f"[green]keyphrase table → {out_path}  (LS unique={n_ls}, ET unique={n_et}, total unique={n_all})[/]")
