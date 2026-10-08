"""F-10: morning digest, a read-only render of lane C's ranking (`mbos_economics.digest.build_digest`, C-08).

The ranking is Agent 03's, and this module never re-orders it. It only:
* selects the open Items from the spine (read-only),
* pre-checks that each carries a lane-C engine scorecard. Items scored by anything else (e.g. the
  spine's placeholder scorer) are listed as EXCLUDED with a reason, never silently dropped, and never
  crash the page,
* links every row to its pending card and its provenance.
`title` is listing text: untrusted, and always HTML-escaped by the renderer.
"""

from __future__ import annotations

from typing import Any

OPEN_STATES = ("RESEARCHING", "SCORED", "RECOMMENDED", "AWAITING_APPROVAL", "HELD")
_NEEDS = ("lane", "decision", "derived")
_NEEDS_DERIVED = ("ev_profit_per_hour", "confidence", "ev_decision", "time_to_cash_days")


def _engine_scorecard(item: dict) -> str | None:
    """None if the item has a lane-C scorecard the digest can rank, else the reason it cannot."""
    sc = ((item.get("scores") or {}).get("scorecard")) or None
    if sc is None:
        return None  # build_digest itself reports "not scored yet"
    missing = [k for k in _NEEDS if k not in sc] + [f"derived.{k}" for k in _NEEDS_DERIVED if k not in (sc.get("derived") or {})]
    if missing:
        return f"scorecard is not lane C engine output (missing {', '.join(missing[:3])}); cannot rank"
    return None


def build(store: Any, as_of: str, limit: int | None = None) -> dict:
    """{'digest': <03's digest or None>, 'error': str|None, 'precheck_excluded': [...], 'cards': {item_id: areq_id}}."""
    try:
        from mbos_economics.digest import build_digest
    except ImportError:
        return {"digest": None, "error": "lane C package mbos_economics is not installed", "precheck_excluded": [], "cards": {}}
    items = store.items_in_states(OPEN_STATES)
    ok, pre = [], []
    for it in items:
        why = _engine_scorecard(it)
        (pre.append({"item_id": it["item_id"], "reason": why}) if why else ok.append(it))
    try:
        d = build_digest(ok, as_of, limit=limit)
    except Exception as e:  # noqa: BLE001 — show lane C's failure honestly; never guess a ranking
        return {"digest": None, "error": f"build_digest failed: {type(e).__name__}: {e}", "precheck_excluded": pre, "cards": {}}
    cards = {}
    for r in d["rows"]:
        open_areqs = [a for a in store.action_requests_for_item(r["item_id"]) if a["status"] in ("pending_approval", "held")]
        if open_areqs:
            cards[r["item_id"]] = open_areqs[-1]["action_request_id"]
    return {"digest": d, "error": None, "precheck_excluded": pre, "cards": cards}


def figures(r: dict) -> dict:
    """F-95: ONE figure per concept for a digest row. `priority` is lane C's rank score (unitless, used only to order the list; never
    dollars); `ev` is the expected profit of the decision in dollars; `ev_per_hour` is expected profit per hour. Missing = None."""
    def f(v):
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    return {"priority": f(r.get("rank_score") if r.get("rank_score") is not None else r.get("value_per_hour")),
            "ev": f(r.get("ev_decision")), "ev_per_hour": f(r.get("ev_profit_per_hour"))}


def dollars(v, prefix: str = "$") -> str:
    """Plain text for one figure (callers escape): UNKNOWN stays UNKNOWN."""
    return "UNKNOWN" if v is None else f"{prefix}{v:,.2f}".rstrip("0").rstrip(".")
