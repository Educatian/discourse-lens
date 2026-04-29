"""Per-field keyword co-occurrence networks + cross-field index.

For each field (LS, ET):
- Nodes = keyphrases that appear in >= MIN_NODE_FREQ documents
- Edges = within-doc co-occurrence; weight = NPMI (normalized PMI)
- Filter: NPMI >= MIN_NPMI, raw cooc >= MIN_COOC

Cross-field index: maps each surviving keyphrase to its presence + neighbors
in BOTH fields, used by the frontend's linked-highlight click. Optional fuzzy
matching via embedding cosine for synonym pairs (e.g., "self-regulation" ↔
"self-regulated learning") is precomputed when build_cross_field_index runs
with embeddings provided.
"""
from __future__ import annotations
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from rich.console import Console

from .keywords import is_noise, lemma_collapse_key

console = Console()

# Defaults — tuned 2026-04-28 to densify LS network (was 305 nodes / 50 links).
# Earlier (2/2/0.20) left LS too sparse because KeyBERT's top-5 selection
# fragments vocabulary across LS subcommunities (CSCL / knowledge building / ILS).
# Layered with semantic merge below: synonyms collapse first, then thresholds gate.
MIN_NODE_FREQ = 3
MIN_COOC = 1
MIN_NPMI = 0.10
FUZZY_COSINE_THRESH = 0.85
TOP_NEIGHBORS = 15

# Semantic merge: phrases with cosine >= MERGE_THRESH are folded into one canonical
# form (most-frequent variant within the cluster). 0.80 catches "scaffolding strategies"
# / "instructional scaffolding" without over-merging "scaffolding" / "guidance".
MERGE_THRESH = 0.80


def post_filter_doc_keyphrases(doc_keyphrases: dict[str, list[str]]) -> dict[str, list[str]]:
    """Drop noise + lemma-collapse permutation duplicates per doc.

    Applied here so we don't have to re-run KeyBERT to retune the noise list.
    For each canonical lemma-key we keep the variant that appears most often
    across the whole field (computed from raw doc_keyphrases first).
    """
    from collections import Counter
    variant_freq: Counter = Counter()
    for kps in doc_keyphrases.values():
        for p in set(kps):
            if is_noise(p):
                continue
            variant_freq[p] += 1
    canonical_pick: dict[str, str] = {}
    for variant, n in variant_freq.most_common():
        ck = lemma_collapse_key(variant)
        canonical_pick.setdefault(ck, variant)

    out: dict[str, list[str]] = {}
    for doi, kps in doc_keyphrases.items():
        seen: set[str] = set()
        kept: list[str] = []
        for p in kps:
            if is_noise(p):
                continue
            canon = canonical_pick.get(lemma_collapse_key(p))
            if not canon or canon in seen:
                continue
            kept.append(canon)
            seen.add(canon)
        out[doi] = kept
    return out


def semantic_merge_doc_keyphrases(
    doc_keyphrases: dict[str, list[str]],
    threshold: float = MERGE_THRESH,
    embed_fn=None,
) -> dict[str, list[str]]:
    """Merge near-synonym keyphrases via embedding cosine.

    KeyBERT's top-5 selection per doc fragments vocabulary across papers about
    the same concept ("scaffolding strategies" / "instructional scaffolding" /
    "scaffolding student inquiry"). This pass embeds every surviving phrase,
    union-finds clusters above the cosine threshold, picks the most-frequent
    member as the canonical form, and rewrites doc keyphrase lists.

    Returns rewritten doc_keyphrases. Does not mutate input.
    """
    from collections import Counter
    import numpy as np

    freq: Counter = Counter()
    for kps in doc_keyphrases.values():
        for p in set(kps):
            freq[p] += 1
    phrases = sorted(freq.keys())
    if len(phrases) < 2:
        return doc_keyphrases

    if embed_fn is None:
        from sentence_transformers import SentenceTransformer
        console.print(f"[cyan]semantic merge: embedding {len(phrases)} phrases on CPU...[/]")
        model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")  # MiniLM is enough for short phrases
        def embed_fn(xs):
            v = model.encode(xs, normalize_embeddings=True, show_progress_bar=False)
            return np.asarray(v, dtype=np.float32)
    embeddings = embed_fn(phrases)
    sim = embeddings @ embeddings.T
    np.fill_diagonal(sim, 0.0)

    parent = list(range(len(phrases)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    n = len(phrases)
    # Iterate upper triangle only — sim is symmetric and diag was zeroed
    for i in range(n):
        # Numpy filter: indices j>i with sim above threshold
        js = np.where(sim[i, i+1:] >= threshold)[0]
        for j in js:
            union(i, int(i + 1 + j))

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    # Canonical = most frequent within cluster, ties → shortest then alphabetical
    canonical_map: dict[str, str] = {}
    for members in clusters.values():
        members.sort(key=lambda i: (-freq[phrases[i]], len(phrases[i]), phrases[i]))
        canon = phrases[members[0]]
        for i in members:
            canonical_map[phrases[i]] = canon

    n_merged = sum(1 for p, c in canonical_map.items() if p != c)
    n_clusters_with_merges = sum(1 for ms in clusters.values() if len(ms) > 1)
    console.print(f"[green]semantic merge: {len(phrases)} → {len(clusters)} canonicals "
                  f"({n_merged} variants folded into {n_clusters_with_merges} clusters)[/]")

    out: dict[str, list[str]] = {}
    for doi, kps in doc_keyphrases.items():
        seen: set[str] = set()
        kept: list[str] = []
        for p in kps:
            canon = canonical_map.get(p, p)
            if canon in seen:
                continue
            kept.append(canon)
            seen.add(canon)
        out[doi] = kept
    return out


def build_field_network(
    field: str,
    doc_keyphrases: dict[str, list[str]],
    min_node_freq: int = MIN_NODE_FREQ,
    min_cooc: int = MIN_COOC,
    min_npmi: float = MIN_NPMI,
) -> dict:
    """Returns {nodes: [{id, freq}], links: [{source, target, weight, npmi, cooc}]}."""
    # 0) post-filter: drop noise + collapse permutation duplicates
    doc_keyphrases = post_filter_doc_keyphrases(doc_keyphrases)
    # 0b) semantic merge: collapse near-synonym variants into canonical phrases
    doc_keyphrases = semantic_merge_doc_keyphrases(doc_keyphrases)
    # 1) per-keyphrase doc frequency
    kp_freq: Counter = Counter()
    for kps in doc_keyphrases.values():
        kp_freq.update(set(kps))
    # 2) filter to min frequency
    keep = {p for p, n in kp_freq.items() if n >= min_node_freq}
    if not keep:
        return {"field": field, "nodes": [], "links": []}

    # 3) co-occurrence within doc (only among kept phrases)
    cooc: Counter = Counter()
    for kps in doc_keyphrases.values():
        kept = sorted({p for p in kps if p in keep})
        for i in range(len(kept)):
            for j in range(i + 1, len(kept)):
                cooc[(kept[i], kept[j])] += 1

    # 4) NPMI = ln(p(a,b) / (p(a) p(b))) / -ln(p(a,b))
    n_docs = len(doc_keyphrases)
    if n_docs == 0:
        return {"field": field, "nodes": [], "links": []}

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
        links.append({
            "source": a, "target": b,
            "cooc": c, "npmi": round(npmi, 4),
            # weight is what D3 force layout will use; same as NPMI for now
            "weight": round(npmi, 4),
        })

    console.print(f"[cyan]{field}[/] network: nodes={len(nodes)}  links={len(links)}  (n_docs={n_docs})")
    return {"field": field, "nodes": nodes, "links": links, "n_docs": n_docs}


def top_neighbors(net: dict, k: int = TOP_NEIGHBORS) -> dict[str, list[dict]]:
    """For each node, sorted top-k neighbors by NPMI weight."""
    adj: dict[str, list[dict]] = defaultdict(list)
    for link in net["links"]:
        adj[link["source"]].append({"id": link["target"], "weight": link["weight"], "cooc": link["cooc"]})
        adj[link["target"]].append({"id": link["source"], "weight": link["weight"], "cooc": link["cooc"]})
    for node in adj:
        adj[node] = sorted(adj[node], key=lambda x: x["weight"], reverse=True)[:k]
    return dict(adj)


def build_cross_field_index(
    net_ls: dict,
    net_et: dict,
    fuzzy_pairs: list[tuple[str, str, float]] | None = None,
) -> dict:
    """{keyphrase: {ls: {freq, neighbors[]}, et: {freq, neighbors[]}, fuzzy_links: [(other_kp, score)]}}.

    Used by the frontend: clicking a node looks up both fields' presence in O(1).
    """
    ls_freq = {n["id"]: n["freq"] for n in net_ls["nodes"]}
    et_freq = {n["id"]: n["freq"] for n in net_et["nodes"]}
    ls_adj = top_neighbors(net_ls)
    et_adj = top_neighbors(net_et)

    fuzzy_index: dict[str, list[tuple[str, float]]] = defaultdict(list)
    if fuzzy_pairs:
        for a, b, score in fuzzy_pairs:
            fuzzy_index[a].append((b, score))
            fuzzy_index[b].append((a, score))

    all_keys = set(ls_freq) | set(et_freq)
    out: dict[str, dict] = {}
    for k in sorted(all_keys):
        out[k] = {
            "ls": {"freq": ls_freq.get(k, 0), "neighbors": ls_adj.get(k, [])},
            "et": {"freq": et_freq.get(k, 0), "neighbors": et_adj.get(k, [])},
            "fuzzy_links": [{"id": o, "score": round(s, 3)} for o, s in fuzzy_index.get(k, [])],
        }
    return out


def compute_fuzzy_synonym_pairs(
    net_ls: dict,
    net_et: dict,
    embed_keyphrase_fn,
    threshold: float = FUZZY_COSINE_THRESH,
    only_one_sided: bool = True,
) -> list[tuple[str, str, float]]:
    """For keyphrases that appear in only one field, find near-duplicates in the other.

    `embed_keyphrase_fn(list[str]) -> np.ndarray` should produce L2-normalized embeddings.
    Returns list of (ls_kp, et_kp, cosine_score) above threshold.
    """
    import numpy as np

    ls_kps = [n["id"] for n in net_ls["nodes"]]
    et_kps = [n["id"] for n in net_et["nodes"]]

    if only_one_sided:
        ls_set, et_set = set(ls_kps), set(et_kps)
        ls_kps = [k for k in ls_kps if k not in et_set]
        et_kps = [k for k in et_kps if k not in ls_set]

    if not ls_kps or not et_kps:
        return []

    a = embed_keyphrase_fn(ls_kps)   # (Nl, d)
    b = embed_keyphrase_fn(et_kps)   # (Ne, d)
    sim = a @ b.T                    # cosine if both L2-normalized
    pairs: list[tuple[str, str, float]] = []
    for i in range(sim.shape[0]):
        for j in range(sim.shape[1]):
            if sim[i, j] >= threshold:
                pairs.append((ls_kps[i], et_kps[j], float(sim[i, j])))
    pairs.sort(key=lambda x: -x[2])
    return pairs


def save_networks(
    net_ls: dict, net_et: dict, cross_index: dict, out_dir: str | Path,
) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "network_ls.json").write_text(json.dumps(net_ls, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "network_et.json").write_text(json.dumps(net_et, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "keyword_index.json").write_text(json.dumps(cross_index, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]wrote network_ls.json, network_et.json, keyword_index.json → {out_dir}[/]")
