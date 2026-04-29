"""The 6 target journals — single source of truth.

Field assignment is editorial, not algorithmic: LS = Learning Sciences,
ET = Educational Technology / Instructional Design.

Multiple ISSNs per journal are fallbacks; the first that returns
non-zero results from OpenAlex wins (validated by the smoke test).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

Field = Literal["LS", "ET"]


@dataclass(frozen=True)
class Journal:
    id: str            # short slug, used in JSON output
    name: str          # display name
    field: Field
    issns: tuple[str, ...]  # OpenAlex issn filter accepts comma-sep; we try each


JOURNALS: tuple[Journal, ...] = (
    # Learning Sciences side
    Journal("jls",   "Journal of the Learning Sciences",         "LS", ("1050-8406", "1532-7809")),
    Journal("isci",  "Instructional Science",                    "LS", ("0020-4277", "1573-1952")),
    Journal("ijcscl","IJCSCL",                                   "LS", ("1556-1607", "1556-1615")),
    Journal("ils",   "Information and Learning Sciences",        "LS", ("2398-5348", "2398-5356")),

    # Educational Technology / AECT side
    Journal("etrd",  "ETR&D",                                    "ET", ("1042-1629", "1556-6501")),
    Journal("tt",    "TechTrends",                               "ET", ("8756-3894", "1559-7075")),
    Journal("ijdl",  "IJDL",                                     "ET", ("2159-449X",)),
    Journal("jaid",  "Journal of Applied Instructional Design",  "ET", ("2160-5289",)),
    Journal("jfdl",  "Journal of Formative Design in Learning",  "ET", ("2509-8039", "2509-8047")),
)

JOURNAL_BY_ID: dict[str, Journal] = {j.id: j for j in JOURNALS}
