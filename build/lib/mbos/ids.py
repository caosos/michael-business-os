"""Prefixed ULIDs (ADR-0004, conflict C6). Public ids are `<prefix>_<26 Crockford chars>`.

Inside a DBOS workflow, generate ids only inside steps/transactions, never in the
workflow body: step outputs are checkpointed, so replays reuse the same id.
"""

from __future__ import annotations

from ulid import ULID

PREFIXES = {
    "item": "itm",
    "provenance": "prov",
    "action_request": "areq",
    "approval": "appr",
    "receipt": "rcpt",
    "outcome": "outc",
    "scorecard": "scr",
    "recommendation": "rec",
}


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES.values():
        raise ValueError(f"unknown id prefix {prefix!r}")
    return f"{prefix}_{ULID()}"
