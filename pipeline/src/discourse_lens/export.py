"""Export pipeline artifacts to web/public/data/*.json for the frontend.

Frontend reads these as static JSON; nothing else needs to be served.
"""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

from rich.console import Console

from .cache import Cache
from .journals import JOURNALS, JOURNAL_BY_ID

console = Console()


def export_papers_index(cache: Cache, out_path: Path) -> int:
    """One row per paper: minimal info for tooltips + neighbor drilldowns."""
    rows = []
    for r in cache.iter_abstracts():
        rows.append({
            "doi": r["doi"],
            "title": r["title"],
            "journal_id": r["journal_id"],
            "field": r["field"],
            "year": r["year"],
            "authors": r["authors"][:6],   # cap to keep JSON small
            "abstract": r["abstract"],
        })
    out_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]papers.json ({len(rows)} rows) → {out_path}[/]")
    return len(rows)


def export_journals_meta(cache: Cache, out_path: Path) -> dict:
    """Static metadata for journals + per-journal counts (for legend + regularize)."""
    counts = cache.count_by_journal()
    meta = {
        "journals": [
            {
                "id": j.id,
                "name": j.name,
                "field": j.field,
                "issns": list(j.issns),
                "count": int(counts.get(j.id, 0)),
            }
            for j in JOURNALS
        ],
        "totals": {
            "ls": sum(counts.get(j.id, 0) for j in JOURNALS if j.field == "LS"),
            "et": sum(counts.get(j.id, 0) for j in JOURNALS if j.field == "ET"),
            "all": sum(counts.values()),
        },
    }
    out_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]journals.json (n={len(meta['journals'])}) → {out_path}[/]")
    return meta


def export_keyword_papers_map(
    keyphrases_json: Path,
    cache: Cache,
    out_path: Path,
) -> None:
    """For each (canonicalized) keyphrase, list of DOIs that mention it (per field).

    Applies the same post-filter + semantic merge as the network builder so
    keyword names in keyword_papers.json match the network nodes (otherwise
    click-to-papers fails for any merged synonym).
    """
    from .network import post_filter_doc_keyphrases, semantic_merge_doc_keyphrases

    agg = json.loads(keyphrases_json.read_text(encoding="utf-8"))
    kw_to_dois: dict[str, dict[str, list[str]]] = {}
    for field_key, field_data in (("ls", agg["ls"]), ("et", agg["et"])):
        filtered = post_filter_doc_keyphrases(field_data["doc_keyphrases"])
        merged = semantic_merge_doc_keyphrases(filtered)
        for doi, kps in merged.items():
            for kp in kps:
                kw_to_dois.setdefault(kp, {"ls": [], "et": []})[field_key].append(doi)
    out_path.write_text(json.dumps(kw_to_dois, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]keyword_papers.json (n_keywords={len(kw_to_dois)}) → {out_path}[/]")


def export_thread_timeline(
    cache: Cache,
    tags_json: Path,
    out_path: Path,
    year_from: int = 2015,
    year_to: int = 2025,
    n_boot: int = 1000,
    n_perm: int = 2000,
) -> None:
    """Year x thread x field counts for TimelineView (stacked area).

    Output schema:
      {
        years: [2015, ..., 2025],
        threads: [{id, display_name, definition}, ...],
        totals_per_year: { ls: [...], et: [...] },   # all papers in year/field
        series: {
          ls: { thread_id: [year_count, ...] },
          et: { thread_id: [...] },
        }
      }

    Skips silently if tags.json is absent (frontend treats it as optional).
    """
    if not tags_json.exists():
        console.print(f"[yellow]thread_timeline skipped: {tags_json} missing[/]")
        return
    tags_data = json.loads(tags_json.read_text(encoding="utf-8"))
    tags = tags_data.get("tags", {})
    threads_meta = tags_data.get("taxonomy", [])
    thread_ids = [t["id"] for t in threads_meta]
    years = list(range(year_from, year_to + 1))
    year_idx = {y: i for i, y in enumerate(years)}

    series = {
        "ls": {tid: [0] * len(years) for tid in thread_ids},
        "et": {tid: [0] * len(years) for tid in thread_ids},
    }
    totals_per_year = {"ls": [0] * len(years), "et": [0] * len(years)}

    paper_by_doi = {r["doi"]: r for r in cache.iter_abstracts()}
    n_tagged = 0
    for doi, rec in tags.items():
        paper = paper_by_doi.get(doi)
        if not paper:
            continue
        field = paper["field"].lower()
        if field not in ("ls", "et"):
            continue
        if paper["year"] not in year_idx:
            continue
        idx = year_idx[paper["year"]]
        totals_per_year[field][idx] += 1
        tids = rec.get("thread_ids") or []
        if tids:
            n_tagged += 1
        for tid in tids:
            if tid in series[field]:
                series[field][tid][idx] += 1

    # Bootstrap percentile 95% CI per (year, field, thread) and bias delta
    # inference per thread. Done in pipeline so the frontend just renders.
    from .stats import bootstrap_yearly_shares, bias_delta_inference
    paper_tags_map = {doi: rec.get("thread_ids") or [] for doi, rec in tags.items()}
    ls_papers_by_year: dict[int, list[str]] = {y: [] for y in years}
    et_papers_by_year: dict[int, list[str]] = {y: [] for y in years}
    ls_all: list[str] = []
    et_all: list[str] = []
    for doi, paper in paper_by_doi.items():
        if paper["year"] not in year_idx:
            continue
        f = paper["field"].lower()
        if f == "ls":
            ls_papers_by_year[paper["year"]].append(doi)
            ls_all.append(doi)
        elif f == "et":
            et_papers_by_year[paper["year"]].append(doi)
            et_all.append(doi)

    console.print(f"[cyan]bootstrap CI: B={n_boot} for {len(years)} years x 2 fields x {len(thread_ids)} threads[/]")
    ls_lo, ls_hi = bootstrap_yearly_shares(ls_papers_by_year, paper_tags_map, thread_ids, years, n_boot=n_boot)
    et_lo, et_hi = bootstrap_yearly_shares(et_papers_by_year, paper_tags_map, thread_ids, years, n_boot=n_boot)
    console.print(f"[cyan]permutation test: B={n_perm} for {len(thread_ids)} thread bias deltas[/]")
    bias = bias_delta_inference(ls_all, et_all, paper_tags_map, thread_ids,
                                n_boot=2000, n_perm=n_perm)

    out = {
        "model": tags_data.get("model"),
        "provider": tags_data.get("provider"),
        "years": years,
        "threads": threads_meta,
        "totals_per_year": totals_per_year,
        "series": series,
        "series_ci": {
            "ls": {"lo": ls_lo, "hi": ls_hi},
            "et": {"lo": et_lo, "hi": et_hi},
        },
        "bias": bias,
        "stats": {
            "n_tagged": n_tagged,
            "n_records": len(tags),
            "n_boot": n_boot,
            "n_perm": n_perm,
        },
    }
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]thread_timeline.json -> {out_path}  (n_tagged={n_tagged}/{len(tags)}, +CI/perm)[/]")


def export_paper_tags(tags_json: Path, out_path: Path) -> None:
    """Per-paper thread tags: {doi: [thread_id, ...]}. Used by DiscourseView/CompareView."""
    if not tags_json.exists():
        console.print(f"[yellow]paper_tags skipped: {tags_json} missing[/]")
        return
    data = json.loads(tags_json.read_text(encoding="utf-8"))
    pt = {
        doi: rec.get("thread_ids", [])
        for doi, rec in data.get("tags", {}).items()
    }
    out_path.write_text(json.dumps(pt, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]paper_tags.json -> {out_path}  (n={len(pt)})[/]")


def export_all(cache_path: str | Path, web_data_dir: str | Path) -> None:
    cache = Cache(cache_path)
    out = Path(web_data_dir)
    out.mkdir(parents=True, exist_ok=True)

    export_papers_index(cache, out / "papers.json")
    export_journals_meta(cache, out / "journals.json")

    # The network artifacts are written directly by network.py to the artifacts/ dir.
    # Mirror them into web/public/data/ so the frontend can fetch them.
    artifacts = Path(cache_path).parent / "artifacts"
    for name in ("network_ls.json", "network_et.json", "keyword_index.json"):
        src = artifacts / name
        if src.exists():
            (out / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            console.print(f"[green]{name} mirrored -> {out}[/]")
        else:
            console.print(f"[yellow]{name} missing - run `dlens keyphrase && dlens network` first[/]")

    kp = artifacts / "keyphrases.json"
    if kp.exists():
        export_keyword_papers_map(kp, cache, out / "keyword_papers.json")

    export_thread_timeline(cache, artifacts / "tags.json", out / "thread_timeline.json")
    export_paper_tags(artifacts / "tags.json", out / "paper_tags.json")
