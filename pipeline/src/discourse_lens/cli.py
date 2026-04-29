"""CLI entry point: dlens ingest | clean | embed | topics | network | tag | export | all."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="discourse-lens: LS x ET journal abstract pipeline", no_args_is_help=True)
console = Console()

PROJECT_ROOT = Path(__file__).resolve().parents[3]   # discourse-lens/
DATA_ROOT = PROJECT_ROOT / "pipeline" / "data"


@app.command()
def ingest(
    journal: Optional[str] = typer.Option(None, help="Restrict to one journal_id (jls, isci, ijcscl, etrd, tt, ijdl)"),
    year_from: int = typer.Option(2015),
    year_to: int = typer.Option(2025),
    max_per_journal: Optional[int] = typer.Option(None, help="Stop after N papers per journal (smoke testing)"),
):
    """Pull abstracts from OpenAlex (with Crossref fallback for missing abstracts)."""
    from .ingest.openalex import ingest_all
    stats = ingest_all(
        DATA_ROOT / "cache.sqlite",
        only_journal=journal,
        year_from=year_from,
        year_to=year_to,
        max_per_journal=max_per_journal,
    )
    _print_ingest_table(stats)


@app.command()
def report():
    """Print current cache contents."""
    from .cache import Cache
    cache = Cache(DATA_ROOT / "cache.sqlite")
    counts = cache.count_by_journal()
    t = Table(title=f"discourse-lens cache — total={sum(counts.values())}")
    t.add_column("journal_id"); t.add_column("count", justify="right")
    for jid, n in sorted(counts.items()):
        t.add_row(jid, str(n))
    console.print(t)


@app.command()
def embed():
    """Compute MPNet embeddings for the cached corpus."""
    from .embed import embed_corpus
    embed_corpus(DATA_ROOT / "cache.sqlite",
                 DATA_ROOT / "artifacts" / "embeddings.npy")


@app.command()
def keyphrase(top_n: int = typer.Option(5, help="Top-N keyphrases per abstract")):
    """Extract keyphrases via KeyBERT and aggregate per field."""
    import json as _json
    from .embed import load_corpus
    from .cache import Cache
    from .keywords import extract_keyphrases, aggregate_per_field, save_keyphrase_table
    cache = Cache(DATA_ROOT / "cache.sqlite")
    rows, docs = load_corpus(cache)
    kps = extract_keyphrases(rows, docs, top_n=top_n)
    agg = aggregate_per_field(rows, kps)
    save_keyphrase_table(agg, DATA_ROOT / "artifacts" / "keyphrases.json")


@app.command()
def network(
    fuzzy: bool = typer.Option(False, help="Compute fuzzy synonym links across fields (slower; uses MPNet embeddings)"),
):
    """Build per-field co-occurrence networks + cross-field index."""
    import json as _json
    from .keywords import KEYBERT_MODEL
    from .network import (build_field_network, build_cross_field_index,
                          compute_fuzzy_synonym_pairs, save_networks)

    kp_path = DATA_ROOT / "artifacts" / "keyphrases.json"
    if not kp_path.exists():
        console.print(f"[red]missing {kp_path}; run `dlens keyphrase` first[/]")
        raise typer.Exit(1)
    agg = _json.loads(kp_path.read_text(encoding="utf-8"))

    net_ls = build_field_network("LS", agg["ls"]["doc_keyphrases"])
    net_et = build_field_network("ET", agg["et"]["doc_keyphrases"])

    fuzzy_pairs: list = []
    if fuzzy:
        from sentence_transformers import SentenceTransformer
        import numpy as _np
        model = SentenceTransformer(KEYBERT_MODEL)
        def _embed(phrases: list[str]):
            v = model.encode(phrases, normalize_embeddings=True, show_progress_bar=False)
            return _np.asarray(v, dtype=_np.float32)
        fuzzy_pairs = compute_fuzzy_synonym_pairs(net_ls, net_et, _embed)
        console.print(f"fuzzy synonym pairs: {len(fuzzy_pairs)}")

    cross = build_cross_field_index(net_ls, net_et, fuzzy_pairs)
    save_networks(net_ls, net_et, cross, DATA_ROOT / "artifacts")


@app.command()
def tag(
    mode: str = typer.Option("parallel", help="sync (sequential) or parallel (asyncio, default)"),
    limit: Optional[int] = typer.Option(None, help="Tag only first N abstracts (smoke test)"),
    model: Optional[str] = typer.Option(None, help="OpenRouter model id; default anthropic/claude-sonnet-4.5"),
    concurrency: int = typer.Option(10, help="Parallel mode concurrency cap"),
):
    """LLM-tag abstracts against the 7-thread discourse taxonomy via OpenRouter."""
    from .tag_llm import tag_abstracts_sync, tag_abstracts_parallel
    out = DATA_ROOT / "artifacts" / "tags.json"
    if mode == "sync":
        tag_abstracts_sync(DATA_ROOT / "cache.sqlite", out, limit=limit, model=model)
    elif mode == "parallel":
        tag_abstracts_parallel(DATA_ROOT / "cache.sqlite", out, limit=limit,
                               model=model, concurrency=concurrency)
    else:
        raise typer.BadParameter("mode must be 'sync' or 'parallel'")


@app.command()
def bertopic(
    min_cluster_size: int = typer.Option(10, help="HDBSCAN min_cluster_size"),
):
    """BERTopic clustering -> topics.json + topic_thread_confusion.json (construct validity)."""
    from .topics import run_bertopic_validity
    out_dir = Path(__file__).resolve().parents[3] / "web" / "public" / "data"
    artifacts = DATA_ROOT / "artifacts"
    run_bertopic_validity(
        cache_path=DATA_ROOT / "cache.sqlite",
        embeddings_path=artifacts / "embeddings.npy",
        tags_path=artifacts / "tags.json",
        out_topics=out_dir / "topics.json",
        out_confusion=out_dir / "topic_thread_confusion.json",
        min_cluster_size=min_cluster_size,
    )


@app.command()
def sensitivity():
    """Parameter sweep -> sensitivity.json (cosine merge + NPMI thresholds)."""
    from .sensitivity import run_sensitivity
    out_dir = Path(__file__).resolve().parents[3] / "web" / "public" / "data"
    run_sensitivity(
        keyphrases_json=DATA_ROOT / "artifacts" / "keyphrases.json",
        out_path=out_dir / "sensitivity.json",
    )


@app.command()
def export(
    web_data: Path = typer.Option(
        Path(__file__).resolve().parents[3] / "web" / "public" / "data",
        help="Output directory (web/public/data by default)",
    ),
):
    """Export all artifacts to web/public/data/*.json for the frontend."""
    from .export import export_all
    export_all(DATA_ROOT / "cache.sqlite", web_data)


def _print_ingest_table(stats: dict) -> None:
    t = Table(title=f"Ingest run {stats.get('run_id')}")
    t.add_column("journal_id"); t.add_column("count", justify="right")
    for jid, n in sorted(stats.get("per_journal_counts", {}).items()):
        t.add_row(jid, str(n))
    console.print(t)
    console.print(f"crossref_filled: {stats.get('crossref_filled', 0)}, "
                  f"openalex_zero_abstract: {stats.get('openalex_zero_abstract', 0)}")
    if errs := stats.get("errors"):
        console.print(f"[red]errors ({len(errs)}):[/]")
        for e in errs[:10]:
            console.print(f"  {e}")


if __name__ == "__main__":
    app()
