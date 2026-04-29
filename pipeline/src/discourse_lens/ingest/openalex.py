"""OpenAlex ingest with Crossref fallback for missing abstracts.

Pulls works for each target journal (by ISSN), decodes the inverted-index
abstract format, and falls back to Crossref for papers OpenAlex returns
without abstracts. Idempotent: re-runs skip DOIs already cached.
"""
from __future__ import annotations
import re
import uuid
from pathlib import Path
from typing import Iterator, Optional

from rich.console import Console

from ..cache import Cache, now_utc
from ..http import CONTACT, FetchClient
from ..journals import JOURNALS, Journal
from ..schemas import JournalAbstract

console = Console()

OPENALEX_WORKS = "https://api.openalex.org/works"
CROSSREF_WORKS = "https://api.crossref.org/works"

# Strip publisher boilerplate like "© 2023 Wiley Periodicals, LLC."
BOILERPLATE_RE = re.compile(
    r"(©|\(c\)|copyright)\s*\d{4}.{0,200}?(?=\s+[A-Z]|$)",
    re.IGNORECASE | re.DOTALL,
)

# Crossref returns abstracts wrapped in JATS XML like <jats:p>...</jats:p>
JATS_TAG_RE = re.compile(r"</?jats:[^>]+>")


def decode_inverted_index(idx: dict[str, list[int]] | None) -> str:
    """OpenAlex abstracts come as {word: [positions]}. Reconstruct flat text."""
    if not idx:
        return ""
    pos_to_word: dict[int, str] = {}
    for word, positions in idx.items():
        for p in positions:
            pos_to_word[p] = word
    if not pos_to_word:
        return ""
    return " ".join(pos_to_word[i] for i in sorted(pos_to_word))


def clean_abstract(text: str) -> str:
    if not text:
        return ""
    text = JATS_TAG_RE.sub("", text)
    text = BOILERPLATE_RE.sub("", text)
    return " ".join(text.split())  # collapse whitespace


def working_issn(client: FetchClient, journal: Journal, year_from: int, year_to: int) -> Optional[str]:
    """Find the first ISSN that returns non-zero results for the date window."""
    for issn in journal.issns:
        try:
            data = client.get_json(
                OPENALEX_WORKS,
                params={
                    "filter": (
                        f"primary_location.source.issn:{issn},"
                        f"from_publication_date:{year_from}-01-01,"
                        f"to_publication_date:{year_to}-12-31,"
                        f"type:article"
                    ),
                    "per-page": "1",
                    "mailto": CONTACT,
                },
            )
        except Exception as e:
            console.print(f"  [yellow]issn {issn} probe failed: {e}[/]")
            continue
        if (data.get("meta") or {}).get("count", 0) > 0:
            return issn
    return None


def iter_openalex_works(client: FetchClient, issn: str, year_from: int, year_to: int) -> Iterator[dict]:
    """Cursor-paginated iterator over works."""
    cursor = "*"
    page = 0
    while cursor:
        page += 1
        data = client.get_json(
            OPENALEX_WORKS,
            params={
                "filter": (
                    f"primary_location.source.issn:{issn},"
                    f"from_publication_date:{year_from}-01-01,"
                    f"to_publication_date:{year_to}-12-31,"
                    f"type:article"
                ),
                "per-page": "100",
                "cursor": cursor,
                "mailto": CONTACT,
            },
        )
        results = data.get("results") or []
        for w in results:
            yield w
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not results:
            break


def fetch_crossref_abstract(client: FetchClient, doi: str) -> str:
    """Crossref fallback for papers OpenAlex didn't return an abstract for."""
    if not doi:
        return ""
    try:
        data = client.get_json(f"{CROSSREF_WORKS}/{doi}", params={"mailto": CONTACT})
    except Exception:
        return ""
    msg = data.get("message") or {}
    raw = msg.get("abstract") or ""
    return clean_abstract(raw)


def ingest_journal(
    client: FetchClient,
    cache: Cache,
    run_id: str,
    journal: Journal,
    year_from: int,
    year_to: int,
    max_n: Optional[int],
) -> tuple[int, int, int, list[str]]:
    """Returns (saved, crossref_filled, openalex_zero, errors)."""
    issn = working_issn(client, journal, year_from, year_to)
    if not issn:
        return 0, 0, 0, [f"{journal.id}: no working ISSN"]

    saved = 0
    crossref_filled = 0
    openalex_zero = 0
    errors: list[str] = []

    console.rule(f"[bold cyan]{journal.id}[/]  ({journal.field})  issn={issn}  {year_from}-{year_to}")

    for w in iter_openalex_works(client, issn, year_from, year_to):
        if max_n is not None and saved >= max_n:
            break
        doi_full = (w.get("doi") or "").strip()
        if not doi_full:
            continue
        doi = doi_full.replace("https://doi.org/", "").lower()
        if cache.has_doi(doi):
            continue

        title = (w.get("title") or "").strip()
        if not title:
            continue
        year = w.get("publication_year") or 0
        if not isinstance(year, int):
            continue

        abstract = clean_abstract(decode_inverted_index(w.get("abstract_inverted_index")))
        source = "openalex"
        if not abstract:
            openalex_zero += 1
            abstract = fetch_crossref_abstract(client, doi)
            if abstract:
                source = "crossref"
                crossref_filled += 1
            else:
                # No abstract anywhere — skip; topic modelling needs the text.
                continue

        authors = []
        for auth in (w.get("authorships") or []):
            n = ((auth.get("author") or {}).get("display_name") or "").strip()
            if n:
                authors.append(n)

        rec = JournalAbstract(
            doi=doi,
            journal_id=journal.id,
            field=journal.field,
            title=title,
            abstract=abstract,
            year=int(year),
            authors=authors,
            issn_used=issn,
            openalex_id=(w.get("id") or "").rsplit("/", 1)[-1] or None,
            abstract_source=source,
            ingest_run_id=run_id,
            ingest_time=now_utc(),
        )
        try:
            cache.upsert_abstract(rec)
            saved += 1
            if saved % 50 == 0:
                console.print(f"  saved={saved}  crossref_filled={crossref_filled}")
        except Exception as e:
            errors.append(f"{journal.id} {doi}: {type(e).__name__}: {e}")

    console.print(f"[green]{journal.id}: saved={saved}  crossref_filled={crossref_filled}  openalex_zero={openalex_zero}[/]")
    return saved, crossref_filled, openalex_zero, errors


def ingest_all(
    cache_path: str | Path,
    only_journal: Optional[str] = None,
    year_from: int = 2015,
    year_to: int = 2025,
    max_per_journal: Optional[int] = None,
) -> dict:
    cache = Cache(cache_path)
    run_id = f"ingest_{now_utc().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"
    cache.open_run(run_id)

    client = FetchClient()
    per_journal: dict[str, int] = {}
    crossref_total = 0
    openalex_zero_total = 0
    all_errors: list[str] = []

    try:
        for j in JOURNALS:
            if only_journal and j.id != only_journal:
                continue
            saved, cf, oz, errs = ingest_journal(
                client, cache, run_id, j, year_from, year_to, max_per_journal,
            )
            per_journal[j.id] = saved
            crossref_total += cf
            openalex_zero_total += oz
            all_errors.extend(errs)
    finally:
        client.close()

    cache.close_run(run_id, per_journal, crossref_total, openalex_zero_total, all_errors)
    return {
        "run_id": run_id,
        "per_journal_counts": per_journal,
        "crossref_filled": crossref_total,
        "openalex_zero_abstract": openalex_zero_total,
        "errors": all_errors,
    }
