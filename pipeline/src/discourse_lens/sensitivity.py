"""Parameter sensitivity sweeps for keyword network robustness.

Two sweeps:
  - cosine_merge: vary semantic-merge cosine threshold; measure top-K keyword
    set Jaccard against the locked reference (0.80).
  - npmi: vary edge NPMI threshold (semantic-merge fixed at reference);
    measure neighbor-set Jaccard for top-K keywords against reference (0.2).

Outputs sensitivity.json. Cached embedding lookup avoids re-encoding the
phrase vocabulary across sweep points.
"""
from __future__ import annotations
import json
import math
from collections import Counter
from pathlib import Path
from typing import Iterable

import numpy as np
from rich.console import Console

console = Console()


def _top_k(doc_keyphrases: dict[str, list[str]], k: int) -> list[str]:
    freq: Counter = Counter()
    for kps in doc_keyphrases.values():
        for p in set(kps):
            freq[p] += 1
    return [p for p, _ in freq.most_common(k)]


def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / max(len(sa | sb), 1)


def _build_edges(
    doc_keyphrases: dict[str, list[str]],
    min_node_freq: int = 3,
    min_cooc: int = 2,
    min_npmi: float = 0.2,
) -> dict:
    """Network build assuming doc_keyphrases is already merged."""
    kp_freq: Counter = Counter()
    for kps in doc_keyphrases.values():
        kp_freq.update(set(kps))
    keep = {p for p, n in kp_freq.items() if n >= min_node_freq}
    if not keep:
        return {"nodes": [], "links": []}

    cooc: Counter = Counter()
    for kps in doc_keyphrases.values():
        kept = sorted({p for p in kps if p in keep})
        for i in range(len(kept)):
            for j in range(i + 1, len(kept)):
                cooc[(kept[i], kept[j])] += 1

    n_docs = len(doc_keyphrases)
    nodes = [{"id": p, "freq": kp_freq[p]} for p in sorted(keep)]
    links: list[dict] = []
    for (a, b), c in cooc.items():
        if c < min_cooc:
            continue
        p_ab = c / n_docs
        p_a = kp_freq[a] / n_docs
        p_b = kp_freq[b] / n_docs
        if p_ab <= 0 or p_a <= 0 or p_b <= 0:
            continue
        denom = -math.log(p_ab)
        if denom <= 0:
            continue
        npmi = math.log(p_ab / (p_a * p_b)) / denom
        if npmi < min_npmi:
            continue
        links.append({"source": a, "target": b, "cooc": c, "npmi": npmi})
    return {"nodes": nodes, "links": links}


def _top_neighbors(net: dict, k: int = 10) -> dict[str, set[str]]:
    adj: dict[str, list[tuple[str, float]]] = {}
    for link in net["links"]:
        adj.setdefault(link["source"], []).append((link["target"], link["npmi"]))
        adj.setdefault(link["target"], []).append((link["source"], link["npmi"]))
    return {n: {x[0] for x in sorted(v, key=lambda z: -z[1])[:k]} for n, v in adj.items()}


def run_sensitivity(
    keyphrases_json: Path,
    out_path: Path,
    cosine_values: list[float] | None = None,
    npmi_values: list[float] | None = None,
    ref_cosine: float = 0.80,
    ref_npmi: float = 0.2,
    top_k_keywords: int = 30,
    top_k_neighbors_per_node: int = 10,
    n_focus_nodes: int = 20,
) -> None:
    cosine_values = cosine_values or [0.70, 0.75, 0.80, 0.85, 0.90]
    npmi_values = npmi_values or [0.10, 0.15, 0.20, 0.25, 0.30]

    from sentence_transformers import SentenceTransformer
    from .network import semantic_merge_doc_keyphrases, post_filter_doc_keyphrases

    agg = json.loads(keyphrases_json.read_text(encoding="utf-8"))
    fields_dk = {
        "ls": post_filter_doc_keyphrases(agg["ls"]["doc_keyphrases"]),
        "et": post_filter_doc_keyphrases(agg["et"]["doc_keyphrases"]),
    }

    console.print("[cyan]loading MiniLM once for sensitivity sweep...[/]")
    model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")

    cosine_result = {"ref": ref_cosine, "top_k": top_k_keywords, "fields": {}}
    npmi_result = {"ref": ref_npmi, "n_focus_nodes": n_focus_nodes,
                   "top_k_neighbors": top_k_neighbors_per_node, "fields": {}}

    for field, dk in fields_dk.items():
        all_phrases = sorted({p for kps in dk.values() for p in kps})
        console.print(f"[cyan]{field}: encoding {len(all_phrases)} phrases once[/]")
        emb = np.asarray(
            model.encode(all_phrases, normalize_embeddings=True, show_progress_bar=False),
            dtype=np.float32,
        )
        emb_lookup = dict(zip(all_phrases, emb))
        def embed_fn(xs, _lookup=emb_lookup):
            return np.stack([_lookup[x] for x in xs])

        # Cosine sweep
        ref_merged = semantic_merge_doc_keyphrases(dk, threshold=ref_cosine, embed_fn=embed_fn)
        ref_top = _top_k(ref_merged, top_k_keywords)
        cosine_rows = []
        for c in cosine_values:
            merged = (
                ref_merged if abs(c - ref_cosine) < 1e-9
                else semantic_merge_doc_keyphrases(dk, threshold=c, embed_fn=embed_fn)
            )
            n_canon = len({p for kps in merged.values() for p in kps})
            top = _top_k(merged, top_k_keywords)
            cosine_rows.append({
                "cosine": c,
                "n_canonicals": n_canon,
                "top_k_jaccard": round(_jaccard(top, ref_top), 4),
            })
        cosine_result["fields"][field] = cosine_rows

        # NPMI sweep — fix merging at ref_cosine
        ref_net = _build_edges(ref_merged, min_npmi=ref_npmi)
        ref_neigh = _top_neighbors(ref_net, k=top_k_neighbors_per_node)
        focus_nodes = [n["id"] for n in
                       sorted(ref_net["nodes"], key=lambda n: -n["freq"])[:n_focus_nodes]]
        npmi_rows = []
        for npmi in npmi_values:
            net = (
                ref_net if abs(npmi - ref_npmi) < 1e-9
                else _build_edges(ref_merged, min_npmi=npmi)
            )
            neigh = _top_neighbors(net, k=top_k_neighbors_per_node)
            jaccards = []
            for nid in focus_nodes:
                a, b = ref_neigh.get(nid, set()), neigh.get(nid, set())
                if not a and not b:
                    continue
                jaccards.append(len(a & b) / max(len(a | b), 1))
            avg = sum(jaccards) / max(len(jaccards), 1)
            npmi_rows.append({
                "npmi": npmi,
                "n_links": len(net["links"]),
                "neighbor_jaccard": round(avg, 4),
            })
        npmi_result["fields"][field] = npmi_rows

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "cosine_merge_sweep": cosine_result,
        "npmi_sweep": npmi_result,
        "interpretation": (
            "Top-K Jaccard near 1.0 means top keywords stay stable across the "
            "parameter range. Neighbor-set Jaccard near 1.0 means the most-frequent "
            "nodes have the same neighbor profile across NPMI thresholds. Both "
            "support that the headline findings are not artifacts of threshold choice."
        ),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]sensitivity.json -> {out_path}[/]")
