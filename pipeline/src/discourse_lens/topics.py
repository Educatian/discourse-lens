"""BERTopic clustering for construct-validity check against LLM thread tagging.

Reuses the cached MPNet embeddings (so this is fast — no re-encoding) plus the
existing tags.json. Outputs:
  - topics.json:   per-topic top words, size, exemplar DOIs
  - topic_thread_confusion.json:   |topic ∩ thread| matrix + diagonal alignment score
"""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

import numpy as np
from rich.console import Console

console = Console()


def run_bertopic_validity(
    cache_path: Path,
    embeddings_path: Path,
    tags_path: Path,
    out_topics: Path,
    out_confusion: Path,
    min_cluster_size: int = 15,
    seed: int = 42,
) -> None:
    from bertopic import BERTopic
    from umap import UMAP
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer
    from .cache import Cache
    from .prep import doc_for_embedding

    cache = Cache(cache_path)
    rows = list(cache.iter_abstracts())
    docs = [doc_for_embedding(r["title"], r["abstract"]) for r in rows]
    dois = [r["doi"] for r in rows]

    # Try cached embeddings first; fall back to fresh CPU MiniLM encoding if
    # row count mismatches (corpus changed since `dlens embed`) or file
    # missing. MiniLM is enough for clustering and avoids the GPU sm_120
    # compatibility issue on RTX 5060 Ti.
    embs: np.ndarray | None = None
    if embeddings_path.exists():
        cached = np.load(embeddings_path)
        if cached.shape[0] == len(docs):
            embs = cached
            console.print(f"[cyan]using cached embeddings: {cached.shape}[/]")
        else:
            console.print(
                f"[yellow]cached embeddings ({cached.shape[0]} rows) != corpus "
                f"({len(docs)}); re-encoding with MiniLM on CPU[/]"
            )
    if embs is None:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
        console.print(f"[cyan]encoding {len(docs)} docs with MiniLM (CPU)...[/]")
        embs = np.asarray(
            model.encode(docs, normalize_embeddings=True, show_progress_bar=True, batch_size=32),
            dtype=np.float32,
        )

    # MiniLM embeddings are flatter than MPNet for short academic abstracts;
    # use more UMAP components and a smaller HDBSCAN floor so clusters
    # actually separate. Without this, n_topics collapses to ~1.
    umap_model = UMAP(
        n_neighbors=12, n_components=10, min_dist=0.0, metric="cosine", random_state=seed
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=max(min_cluster_size, 1),
        min_samples=5,
        metric="euclidean",
        cluster_selection_method="eom",
        prediction_data=True,
    )
    # NOTE: BERTopic feeds the vectorizer per-topic concatenated docs (N rows
    # = N topics), so fractional max_df + integer min_df can collide once
    # there are few topics. Use absolute integer min_df + no upper bound.
    vectorizer = CountVectorizer(stop_words="english", ngram_range=(1, 2),
                                 min_df=2, max_df=1.0)

    topic_model = BERTopic(
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer,
        embedding_model=None,
        verbose=False,
    )
    console.print("[cyan]fitting BERTopic on cached embeddings...[/]")
    topics, _ = topic_model.fit_transform(docs, embeddings=embs)
    info = topic_model.get_topic_info()

    n_outliers = int(sum(1 for t in topics if t == -1))
    console.print(f"[cyan]BERTopic: {len(info)-1} topics + {n_outliers} outliers[/]")

    topics_out: list[dict] = []
    for _, info_row in info.iterrows():
        tid = int(info_row["Topic"])
        if tid == -1:
            continue
        top_words = [w for w, _ in topic_model.get_topic(tid)[:8]]
        idxs = [i for i, t in enumerate(topics) if t == tid]
        if not idxs:
            continue
        # Exemplars: docs closest to topic centroid in embedding space
        centroid = embs[idxs].mean(axis=0)
        sims = embs[idxs] @ centroid / (
            np.linalg.norm(embs[idxs], axis=1) * np.linalg.norm(centroid) + 1e-9
        )
        order = np.argsort(-sims)
        exemplars = []
        for j in order[:3]:
            r = rows[idxs[j]]
            exemplars.append({
                "doi": dois[idxs[j]],
                "title": r["title"],
                "field": r["field"],
                "year": r["year"],
            })
        # Field tilt of the topic
        field_counts = Counter(rows[i]["field"] for i in idxs)
        topics_out.append({
            "id": tid,
            "size": int(info_row["Count"]),
            "top_words": top_words,
            "exemplars": exemplars,
            "ls_count": int(field_counts.get("LS", 0)),
            "et_count": int(field_counts.get("ET", 0)),
        })

    # Confusion matrix
    tags_data = json.loads(Path(tags_path).read_text(encoding="utf-8"))
    paper_tags = {doi: rec.get("thread_ids") or [] for doi, rec in tags_data["tags"].items()}
    thread_ids = [t["id"] for t in tags_data["taxonomy"]]
    thread_names = [t["display_name"] for t in tags_data["taxonomy"]]

    topic_ids_sorted = sorted({t["id"] for t in topics_out})
    confusion = np.zeros((len(topic_ids_sorted), len(thread_ids)), dtype=int)
    for i, tid in enumerate(topic_ids_sorted):
        idxs = [j for j, t in enumerate(topics) if t == tid]
        for j_idx in idxs:
            for thread in paper_tags.get(dois[j_idx], []):
                if thread in thread_ids:
                    confusion[i, thread_ids.index(thread)] += 1

    # Diagonal-ness via Hungarian assignment over top-|threads| topics
    from scipy.optimize import linear_sum_assignment
    n_th = len(thread_ids)
    if confusion.shape[0] >= n_th and confusion.sum() > 0:
        row_sums = confusion.sum(axis=1)
        top_rows = np.argsort(-row_sums)[:n_th]
        sub = confusion[top_rows]
        ri, ci = linear_sum_assignment(-sub)
        diag_score = float(sub[ri, ci].sum() / max(sub.sum(), 1))
    else:
        diag_score = float(np.diag(confusion).sum() / max(confusion.sum(), 1))

    out_topics.parent.mkdir(parents=True, exist_ok=True)
    out_topics.write_text(json.dumps({
        "method": f"BERTopic UMAP15+HDBSCAN(min_cluster_size={min_cluster_size}, seed={seed})",
        "n_topics": len(topics_out),
        "n_outliers": n_outliers,
        "topics": topics_out,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    out_confusion.write_text(json.dumps({
        "method": "BERTopic data clusters vs LLM thread tags",
        "topic_ids": topic_ids_sorted,
        "thread_ids": thread_ids,
        "thread_display_names": thread_names,
        "confusion": confusion.tolist(),
        "diagonal_score": diag_score,
        "interpretation": (
            "diagonal_score = share of paper-thread mass on the optimal topic-thread "
            "assignment; values near 1.0 mean BERTopic clusters align cleanly with "
            "LLM threads (good construct validity)."
        ),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]topics.json -> {out_topics}  ({len(topics_out)} topics)[/]")
    console.print(f"[green]topic_thread_confusion.json -> {out_confusion}  diagonal={diag_score:.3f}[/]")
