"""P-03-13: feed ``plan_week`` real lane-D data.

``plan_from_documents`` is pure: it takes the documents lane D serves (``mbos.v_mission_current.doc``,
``mbos.capital_position_document()``, ``mbos.v_item_documents.doc`` of live Items) and returns a
``mission_plan`` the UI can show. ``plan_from_db`` reads those three through any DB-API cursor.

Nothing is invented. A missing ledger is an all-zero ledger (nothing available to deploy) and is listed in
``unknowns``; a missing mission is a null target and null hours over the caller's period; no scored live
Item means no legs and ``DO_NOT_SPEND`` (``UNKNOWN`` when the target is also unknown).
"""

from __future__ import annotations

from typing import Any

from .mission import _candidate, _period_days, plan_week

LIVE_EXCLUDED = ("DONE", "CLOSED", "REJECTED", "ARCHIVED", "EXPIRED")
_ZERO_LEDGER = {"protected_principal": 0, "earned_working_capital": 0, "capital_deployed": 0,
                "realized_profit": 0, "available_to_deploy": 0}


def _live_scored(item: dict) -> bool:
    return (item.get("state") not in LIVE_EXCLUDED and bool((item.get("scores") or {}).get("scorecard")))


def plan_from_documents(mission: dict | None, ledger: dict | None, items: list[dict], *,
                        period: dict[str, str] | None = None) -> dict:
    """``period`` ({start, end}) is required only when ``mission`` is None."""
    unknowns = []
    if mission is None:
        if not period:
            raise ValueError("no mission document: pass period={'start','end'} (it is never guessed)")
        mission = {"mission_version": "1.0.0", "period": period, "weekly_target_usd": None, "hours_available": None}
        unknowns.append("mission (none set)")
    if ledger is None:
        ledger = dict(_ZERO_LEDGER)
        unknowns.append("capital_ledger (none funded: nothing available to deploy)")
    live, skipped = [], []
    days = _period_days(mission)
    for i in (i for i in items if _live_scored(i)):
        try:
            _candidate(i, days)
        except (KeyError, TypeError, IndexError, ValueError, ArithmeticError, AttributeError) as e:
            skipped.append(f"item {i.get('item_id')} skipped: malformed scorecard ({type(e).__name__}: {e})")
        else:
            live.append(i)
    plan = plan_week(mission, ledger, live)
    if not live:
        plan["recommendation"] = "UNKNOWN" if mission.get("weekly_target_usd") is None else "DO_NOT_SPEND"
        plan["explanation"] += " No scored live Items exist: no opportunity is invented, nothing is spent."
        unknowns.append("scored_items (none live)")
    plan["unknowns"] = plan["unknowns"] + unknowns + skipped
    return plan


def plan_from_db(cur: Any, *, period: dict[str, str] | None = None, mode: str = "dry_run") -> dict:
    cur.execute("SELECT doc FROM mbos.v_mission_current")
    row = cur.fetchone()
    mission = row[0] if row else None
    cur.execute("SELECT mbos.capital_position_document(%s)", (mode,))
    row = cur.fetchone()
    ledger = row[0] if row else None
    cur.execute("SELECT doc FROM mbos.v_item_documents WHERE doc ? 'scores' ORDER BY item_id")
    items = [r[0] for r in cur.fetchall()]
    return plan_from_documents(mission, ledger, items, period=period)
