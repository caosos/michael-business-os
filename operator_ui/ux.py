"""UX-only rules the Operator UI keeps under R10: HOLD presets and PIN step-up.

Everything with a side effect (decision rows, receipts, timers, execution) belongs to the
spine (`mbos.spine.decide`) and the DBOS item workflow. This module only turns form input
into the arguments `spine.decide` expects.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mbos.clock import iso
from mbos.spine import requires_step_up  # single source of truth for the step-up rule

LOCAL_TZ = ZoneInfo("America/Chicago")  # Conway / Little Rock, AR

# The spine's workflow honours: hold_until, escalate_after, renotify_after, and the
# `michael_ping` wake (the card's "Wake now" button). FACT (bed7609): it does not yet act
# on new_info / price_change / auction_ending; they are recorded for when lanes B/C send them.
HOLD_PRESETS = {
    "tomorrow_8am": {"label": "Until tomorrow 8am"},
    "24h": {"label": "24 hours", "hours": 24},
    "3d": {"label": "3 days", "hours": 72},
    "new_info": {"label": "Until new info (re-present after 3 days)", "hours": 72,
                 "wake_on": ["new_info", "price_change", "auction_ending", "michael_ping"]},
}
DEFAULT_WAKE_ON = ["time", "michael_ping"]


class InputError(ValueError):
    """Bad form input; nothing was sent to the spine."""


def hold_for(preset: str, now: datetime, hold_until: str | None = None) -> dict:
    """Build the `hold` argument for spine.decide. Every preset sets a concrete hold_until,
    so the spine's default (+24h) never silently overrides Michael's choice."""
    p = HOLD_PRESETS.get(preset)
    if p is None:
        raise InputError(f"unknown HOLD preset {preset!r}")
    if hold_until:
        until = datetime.fromisoformat(hold_until)
        if until.tzinfo is None:
            until = until.replace(tzinfo=LOCAL_TZ)
    elif preset == "tomorrow_8am":
        until = (now.astimezone(LOCAL_TZ) + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    else:
        until = now + timedelta(hours=p["hours"])
    if until <= now:
        raise InputError("hold_until must be in the future")
    return {"hold_until": iso(until), "wake_on": list(p.get("wake_on", DEFAULT_WAKE_ON)), "renotify_after": "PT24H"}


def auth_context(areq: dict, pin: str | None, configured_pin: str | None, session_id: str, decision: str) -> dict:
    """auth_context for spine.decide. YES on an irreversible / money-like request needs a valid
    PIN; with no PIN configured such a YES is refused here (fail closed) before the spine sees it."""
    step_up = False
    if decision == "YES" and requires_step_up(areq):
        if not configured_pin:
            raise InputError("step-up not configured (MBOS_OPERATOR_PIN unset); irreversible/money YES refused")
        if not pin or not hmac.compare_digest(str(pin), str(configured_pin)):
            raise InputError("this action is irreversible or moves money: step-up PIN required")
        step_up = True
    return {"method": "local_pin" if step_up else "localhost_csrf_session", "session_id": session_id, "step_up": step_up}


# ---------------------------------------------------------------- F-09 outcome entry
OUTCOME_KINDS = {
    "flip": ["flip_acquired", "flip_sold", "flip_unsold_salvaged", "flip_repair_failed", "flip_passed_missed"],
    "service": ["service_won", "service_lost", "service_completed", "service_rework", "service_paid"],
    "any": ["wasted_trip", "message_replied", "message_no_reply", "lead_attributed"],
}
OUTCOME_STATES = {"ACTED", "OUTCOME_RECORDED", "FAILED", "ARCHIVED", "REJECTED"}
_NUMBERS = ("revenue", "total_cost", "hours", "days_to_cash")


def outcome_kinds(lane: str) -> list[str]:
    return OUTCOME_KINDS[lane] + OUTCOME_KINDS["any"]


def parse_outcome(item: dict, form: dict) -> tuple[str, dict]:
    """Form → (kind, kwargs for spine.record_outcome). Validates; builds LEARN predicted-vs-actual pairs
    from the item's own economics so lane C can calibrate (sell price, labor hours)."""
    kind = form.get("kind") or ""
    if kind not in outcome_kinds(item["type"]):
        raise InputError(f"outcome kind {kind!r} is not valid for a {item['type']}")
    realized: dict = {}
    for k in _NUMBERS:
        raw = (form.get(k) or "").strip().replace("$", "").replace(",", "")
        if not raw:
            continue
        try:
            v = float(raw)
        except ValueError:
            raise InputError(f"{k} must be a number")
        if not (0 <= v < 10_000_000):
            raise InputError(f"{k} must be between 0 and 10,000,000")
        realized[k] = int(v) if v.is_integer() else v
    if "revenue" in realized and "total_cost" in realized:
        realized["net_profit"] = realized["revenue"] - realized["total_cost"]
    e = item.get("economics") or {}
    pva = []
    if item["type"] == "flip":
        if "revenue" in realized and kind == "flip_sold":
            pva.append({"field": "resale.target_sell_price",
                        "predicted": (e.get("resale") or {}).get("target_sell_price"), "actual": realized["revenue"]})
        if "hours" in realized:
            pva.append({"field": "rehab.labor_hours", "predicted": (e.get("rehab") or {}).get("labor_hours"),
                        "actual": realized["hours"]})
    else:
        if "hours" in realized:
            pva.append({"field": "job.labor_hours", "predicted": (e.get("job") or {}).get("labor_hours"),
                        "actual": realized["hours"]})
        if kind in ("service_won", "service_lost"):
            pva.append({"field": "job.win_prob", "predicted": (e.get("job") or {}).get("win_prob"),
                        "actual": 1 if kind == "service_won" else 0})
    notes = (form.get("notes") or "").strip()[:1000]
    kw = {"realized": realized or None, "predicted_vs_actual": [p for p in pva if p["predicted"] is not None] or None,
          "notes": notes or None}
    return kind, {k: v for k, v in kw.items() if v is not None}
