"""Canonical schemas for journal abstracts and pipeline artifacts."""
from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field

Field_ = Literal["LS", "ET"]
AbstractSource = Literal["openalex", "crossref", "manual"]


class JournalAbstract(BaseModel):
    """One paper from one journal, abstract-level."""
    doi: str
    journal_id: str
    field: Field_
    title: str
    abstract: str
    year: int
    authors: list[str] = Field(default_factory=list)
    issn_used: str
    openalex_id: Optional[str] = None
    abstract_source: AbstractSource = "openalex"

    schema_version: str = "0.1.0"
    ingest_run_id: str
    ingest_time: datetime


class IngestRunStats(BaseModel):
    """Per-run audit summary."""
    run_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    per_journal_counts: dict[str, int] = Field(default_factory=dict)
    crossref_filled: int = 0
    openalex_zero_abstract: int = 0
    errors: list[str] = Field(default_factory=list)
