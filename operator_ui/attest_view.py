"""F-90: "Confirm" a requested evidence key. When the engine is waiting on evidence only Michael can supply (a call with the customer,
the scope of a job), the card shows one form per requested key. Submitting it calls the spine's `record_attestation` (D-29: owner
channel, human actor, receipted); lane C counts it as that evidence on the next re-score, and never invents it.

Human channel only (R14): CSRF + PIN, the author is server-set. Only keys the engine itself requested, and that a person can attest
(`mbos_economics.inputs.ATTESTABLE`), are accepted: a posted key outside that list is refused."""

from __future__ import annotations

import html

from .ux import InputError

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
MAX_NOTE = 300
LABELS = {"customer_screened": "I spoke with the customer and they are real and reachable", "scope_verified": "I verified the scope of the job",
          "price_agreed_in_writing": "The price is agreed in writing", "materials_priced": "I priced the materials",
          "access_and_schedule_confirmed": "Access and schedule are confirmed", "repeat_or_referral": "This is a repeat customer or a referral",
          "remote_verification": "I verified it remotely", "condition_verified": "I verified the condition", "fault_identified": "I identified the fault",
          "title_verified": "I verified the title", "demand_evidence": "I have evidence of demand", "seller_screened": "I spoke with the seller and they check out"}


def requested_keys(item: dict) -> list[str]:
    """Evidence keys the engine asked for on this Item that Michael can attest and has not yet. Empty if lane C is not installed."""
    try:
        from mbos_economics.inputs import ATTESTABLE, attested_keys
    except ImportError:
        return []
    sc = ((item.get("scores") or {}).get("scorecard")) or {}
    asked = list((sc.get("evidence_search") or {}).get("items") or [])
    asked += [k for k, ok in (sc.get("evidence") or {}).items() if not ok and k not in asked]
    ok = ATTESTABLE.get(item.get("type"), set())
    done = set(attested_keys(item))
    return [k for k in asked if k in ok and k not in done]


def parse_note(raw) -> str:
    s = " ".join(str(raw or "").split())
    if any(ord(c) < 32 or ord(c) == 127 for c in s):
        raise InputError("Note has control characters")
    if len(s) < 3:
        raise InputError("Say in a few words how you know (who you spoke to, what you saw)")
    if len(s) > MAX_NOTE:
        raise InputError(f"Note is limited to {MAX_NOTE} characters")
    return s


def render_confirm(item: dict, csrf: str, pin_set: bool, lane_d: bool, nonce: str, reasons=None) -> str:
    keys = requested_keys(item)
    if not keys:
        return ""
    errs = ("<div class='flash err'><b>Not confirmed.</b><ul>" + "".join(f"<li>{e(r)}</li>" for r in reasons) + "</ul></div>") if reasons else ""
    if not (pin_set and lane_d):
        forms = "<p class='bad'>" + ("MBOS_OPERATOR_PIN is not set" if not pin_set else "Confirming needs the lane D store (MBOS_STATE_BACKEND=lane_d)") + \
                ": confirmations cannot be saved from this page (fail-closed).</p>"
    else:
        forms = "".join(
            f"""<form method="post" action="/item/{e(item['item_id'])}/attest"><input type="hidden" name="csrf" value="{e(csrf)}">
<input type="hidden" name="nonce" value="{e(nonce)}{e(i)}"><input type="hidden" name="key" value="{e(k)}">
<div class="decide"><b>{e(LABELS.get(k, k.replace('_', ' ')))}</b> <code>{e(k)}</code>
<label>How do you know?<input name="note" maxlength="{MAX_NOTE}" required></label>
<label>PIN<input name="pin" type="password" autocomplete="off" required></label>
<button class="b-HOLD" style="width:auto">Confirm</button></div></form>""" for i, k in enumerate(keys))
    return ("<div class='card rec' id='confirm'><h2>Confirm what you know</h2><p class='small'>The system is waiting on evidence only you can supply. "
            "Confirming records <b>your word</b> (human, receipted) as that evidence; it is never guessed. Nothing is sent to anyone.</p>"
            f"{errs}{forms}</div>")
