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
    from .mission import nonfinite_paths

    if not isinstance(doc, dict):
        return ["campaign must be an object"]
    errs = [f"{b}: non-finite number is not a valid value" for b in nonfinite_paths(doc)]
    if errs:
        return errs
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


def may_run(doc: Any, now: Any = None) -> bool:
    """True only for a VALID, ACTIVE, unexpired campaign at an autonomy level that only notifies or recommends. Malformed input is
    False (never an exception) and anything above RECOMMEND needs governance (E-17)."""
    from datetime import datetime, timezone

    try:
        if errors(doc):
            return False
        now = now or datetime.now(timezone.utc)
        for exp in ((doc.get("stop_conditions") or {}).get("expires_at"), (doc["autonomy"].get("limits") or {}).get("expires_at")):
            if exp and datetime.fromisoformat(str(exp).replace("Z", "+00:00")) <= now:
                return False
        return doc["autonomy"]["level"] in RUNNABLE_LEVELS and doc["status"] == "ACTIVE"
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
