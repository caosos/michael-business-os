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
