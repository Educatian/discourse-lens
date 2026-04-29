"""OpenAlex ISSN smoke test for the LS×ET discourse map.

Validates that all 6 target journals return abstracts in 2024.
Decision gate before scaffolding the full pipeline.

Run:
    python scripts/openalex_smoke.py
"""
from __future__ import annotations
import json
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass

CONTACT = "jewoong.moon@gmail.com"

JOURNALS = [
    # (display_name, field, [ISSNs])
    ("Journal of the Learning Sciences", "LS", ["1050-8406", "1532-7809"]),
    ("Instructional Science",            "LS", ["0020-4277", "1573-1952"]),
    ("IJCSCL",                           "LS", ["1556-1607", "1556-1615"]),
    ("ETR&D",                            "ET", ["1042-1629", "1556-6501"]),
    ("TechTrends",                       "ET", ["8756-3894", "1559-7075"]),
    ("IJDL",                             "ET", ["2159-449X"]),
]

API = "https://api.openalex.org/works"


@dataclass
class JournalStat:
    name: str
    field: str
    issn: str
    count_2024: int
    sample_n: int
    sample_with_abstract: int

    @property
    def abstract_pct(self) -> float:
        return 100.0 * self.sample_with_abstract / self.sample_n if self.sample_n else 0.0


def query(issn: str) -> dict:
    params = {
        "filter": (
            f"primary_location.source.issn:{issn},"
            f"from_publication_date:2024-01-01,"
            f"to_publication_date:2024-12-31,"
            f"type:article"
        ),
        "per-page": "25",
        "mailto": CONTACT,
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": f"discourse-lens-smoke/0.1 ({CONTACT})"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def assess(issn: str) -> tuple[int, int, int]:
    """Return (total_count, sample_n, sample_with_abstract)."""
    data = query(issn)
    count = int(data.get("meta", {}).get("count", 0))
    results = data.get("results", []) or []
    with_abs = sum(1 for w in results if w.get("abstract_inverted_index"))
    return count, len(results), with_abs


def main() -> int:
    print(f"OpenAlex smoke test — 2024, contact={CONTACT}\n")
    stats: list[JournalStat] = []
    failed: list[str] = []

    for name, field, issns in JOURNALS:
        # Try each ISSN; first one with non-zero count wins.
        chosen: JournalStat | None = None
        for issn in issns:
            try:
                count, sn, sa = assess(issn)
            except Exception as e:
                print(f"  [error] {name} ({issn}): {type(e).__name__}: {e}")
                continue
            if count > 0:
                chosen = JournalStat(name, field, issn, count, sn, sa)
                break
            else:
                print(f"  [zero] {name} ({issn}): no 2024 results")
        if chosen is None:
            failed.append(name)
            print(f"  [FAIL] {name}: no working ISSN")
        else:
            stats.append(chosen)
            print(f"  [ok]   {chosen.name:<40} field={chosen.field}  issn={chosen.issn}"
                  f"  n_2024={chosen.count_2024:>4}  abstracts={chosen.abstract_pct:>5.1f}%")

    print()
    if failed:
        print(f"FAIL: {len(failed)} journal(s) need ISSN fix: {failed}")
        return 2
    total_2024 = sum(s.count_2024 for s in stats)
    est_10y = total_2024 * 10  # rough — many journals expanded over decade
    print(f"OK: 6 journals reachable. 2024 total={total_2024}, rough 10y estimate={est_10y}")
    print(f"Mean abstract coverage: {sum(s.abstract_pct for s in stats) / len(stats):.1f}%")

    # Coverage health gate: any journal under 50% abstract coverage is a yellow flag
    weak = [s for s in stats if s.abstract_pct < 50]
    if weak:
        print(f"\nYELLOW: low abstract coverage in: {[s.name for s in weak]}")
        print("       (Crossref fallback in Stage 1 will need to fill these)")
    else:
        print("\nGREEN: all journals >= 50% abstract coverage in OpenAlex sample")
    return 0


if __name__ == "__main__":
    sys.exit(main())
