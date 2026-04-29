"""SQLite cache for raw abstracts.

Idempotent: re-running ingest skips DOIs already in the table.
Single table; we don't need the content-addressed object store from
ai-literacy-corpus since abstracts are already structured text.
"""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

from .schemas import JournalAbstract


class Cache:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS abstract (
                doi TEXT PRIMARY KEY,
                journal_id TEXT NOT NULL,
                field TEXT NOT NULL,
                title TEXT NOT NULL,
                abstract TEXT NOT NULL,
                year INTEGER NOT NULL,
                authors_json TEXT NOT NULL,
                issn_used TEXT NOT NULL,
                openalex_id TEXT,
                abstract_source TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                ingest_run_id TEXT NOT NULL,
                ingest_time TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_abstract_journal ON abstract(journal_id);
            CREATE INDEX IF NOT EXISTS ix_abstract_field   ON abstract(field);
            CREATE INDEX IF NOT EXISTS ix_abstract_year    ON abstract(year);

            CREATE TABLE IF NOT EXISTS ingest_run (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                per_journal_counts_json TEXT,
                crossref_filled INTEGER DEFAULT 0,
                openalex_zero_abstract INTEGER DEFAULT 0,
                errors_json TEXT
            );
            """)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.db_path)
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---------- abstracts ----------

    def has_doi(self, doi: str) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM abstract WHERE doi=? LIMIT 1", (doi,)).fetchone() is not None

    def upsert_abstract(self, a: JournalAbstract) -> None:
        with self._conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO abstract VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                a.doi, a.journal_id, a.field, a.title, a.abstract, a.year,
                json.dumps(a.authors), a.issn_used, a.openalex_id, a.abstract_source,
                a.schema_version, a.ingest_run_id, a.ingest_time.isoformat(),
            ))

    def count_by_journal(self) -> dict[str, int]:
        with self._conn() as c:
            rows = c.execute("SELECT journal_id, COUNT(*) FROM abstract GROUP BY journal_id").fetchall()
        return {jid: int(n) for jid, n in rows}

    def iter_abstracts(self, journal_id: Optional[str] = None) -> Iterable[dict]:
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            q = "SELECT * FROM abstract"
            args: tuple = ()
            if journal_id:
                q += " WHERE journal_id=?"
                args = (journal_id,)
            for row in c.execute(q, args):
                d = dict(row)
                d["authors"] = json.loads(d.pop("authors_json"))
                yield d

    # ---------- ingest run audit ----------

    def open_run(self, run_id: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO ingest_run(run_id, started_at) VALUES (?,?)",
                (run_id, _now_iso()),
            )

    def close_run(self, run_id: str, per_journal: dict[str, int],
                  crossref_filled: int, openalex_zero: int, errors: list[str]) -> None:
        with self._conn() as c:
            c.execute(
                """UPDATE ingest_run
                   SET finished_at=?, per_journal_counts_json=?,
                       crossref_filled=?, openalex_zero_abstract=?, errors_json=?
                   WHERE run_id=?""",
                (_now_iso(), json.dumps(per_journal), crossref_filled, openalex_zero,
                 json.dumps(errors), run_id),
            )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
