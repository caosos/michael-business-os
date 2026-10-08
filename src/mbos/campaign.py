"""Wanted-campaign contract helpers (ADR-0013, `campaign.schema.json`). A campaign authorises nothing."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .contracts.schemas import ContractViolation, contracts_dir

# Autonomy levels this release may RUN. ASSISTED_DEAL only drafts through step-up approval (E-17); BOUNDED_AUTOPILOT is denied.
RUNNABLE_LEVELS = ("WATCH_ONLY", "RECOMMEND")


@lru_cache(maxsize=1)
def _v() -> Draft202012Validator:
    return Draft202012Validator(json.loads((contracts_dir() / "campaign.schema.json").read_text()), format_checker=FormatChecker())


def errors(doc: Any) -> list[str]:
    errs = [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in _v().iter_errors(doc)]
    if errs:
        return errs
    lim = doc["autonomy"].get("limits") or {}
    if lim.get("max_offer_usd") is not None and lim.get("max_total_spend_usd") is not None and lim["max_offer_usd"] > lim["max_total_spend_usd"]:
        errs.append("limits.max_offer_usd exceeds max_total_spend_usd")
    if lim.get("max_offer_usd") is not None and lim["max_offer_usd"] > doc["criteria"]["max_price_usd"]:
        errs.append("limits.max_offer_usd exceeds criteria.max_price_usd")
    return errs


def validate(doc: Any) -> None:
    errs = errors(doc)
    if errs:
        raise ContractViolation("campaign", errs)


def may_run(doc: dict) -> bool:
    """True only for autonomy levels that act without a human (none) or only notify/recommend. Anything else needs governance."""
    return doc["autonomy"]["level"] in RUNNABLE_LEVELS and doc["status"] == "ACTIVE"
