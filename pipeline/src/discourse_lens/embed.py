"""Sentence-transformer embeddings for the cached corpus.

Uses all-mpnet-base-v2 (768-dim, balanced quality/speed). Caches per-DOI
embeddings to disk so re-running clusters/networks doesn't re-embed.
"""
from __future__ import annotations
from pathlib import Path
from typing import Iterable

import numpy as np
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from .cache import Cache
from .prep import doc_for_embedding, is_english, quality_gate

console = Console()

EMBED_MODEL = "sentence-transformers/all-mpnet-base-v2"


def load_corpus(cache: Cache) -> tuple[list[dict], list[str]]:
    """Load cached abstracts that pass cleaning + quality gates.

    Returns (rows, docs) where rows is metadata-aligned with docs.
    """
    rows: list[dict] = []
    docs: list[str] = []
    skipped = {"too_short": 0, "too_long": 0, "non_english": 0, "empty": 0}
    for r in cache.iter_abstracts():
        text = doc_for_embedding(r["title"], r["abstract"])
        ok, reason = quality_gate(text)
        if not ok:
            skipped[reason.split(" ")[0]] = skipped.get(reason.split(" ")[0], 0) + 1
            continue
        if not is_english(text):
            skipped["non_english"] += 1
            continue
        rows.append(r)
        docs.append(text)
    console.print(f"corpus: {len(rows)} kept, skipped={skipped}")
    return rows, docs


def embed_corpus(cache_path: str | Path, out_path: str | Path) -> tuple[np.ndarray, list[dict]]:
    from sentence_transformers import SentenceTransformer

    cache = Cache(cache_path)
    rows, docs = load_corpus(cache)
    if not docs:
        raise RuntimeError("Empty corpus — nothing to embed.")

    console.print(f"loading {EMBED_MODEL} (first run downloads ~420MB)...")
    model = SentenceTransformer(EMBED_MODEL)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"embedding {len(docs)} abstracts", total=len(docs))
        # encode in batches with progress callback
        batch_size = 32
        all_emb: list[np.ndarray] = []
        for i in range(0, len(docs), batch_size):
            batch = docs[i:i+batch_size]
            emb = model.encode(batch, show_progress_bar=False, normalize_embeddings=True)
            all_emb.append(emb)
            progress.update(task, advance=len(batch))
    embeddings = np.vstack(all_emb).astype(np.float32)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(out_path, embeddings)
    # Save row metadata alongside (DOI order matches embeddings rows)
    import json
    meta_path = out_path.with_suffix(".meta.json")
    meta_path.write_text(
        json.dumps([{"doi": r["doi"], "journal_id": r["journal_id"],
                     "field": r["field"], "year": r["year"],
                     "title": r["title"]} for r in rows], indent=2),
        encoding="utf-8",
    )
    console.print(f"[green]wrote {embeddings.shape} → {out_path}[/]")
    console.print(f"[green]wrote metadata → {meta_path}[/]")
    return embeddings, rows
