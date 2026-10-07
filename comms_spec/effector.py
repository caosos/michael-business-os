"""F-06: CommsDryRunEffector, a DRY-RUN `mbos.interfaces.Effector` for `comms.*` and (binding) `offer.*` capabilities.

It never sends: there are no network imports (test-enforced) and `dry_run` is always True. For every
call it evaluates, in order, the checks a live comms effector must pass, and records them:

  draft present → template integrity → disclosure (E1) → send window (E3) → rate limit → DNC → consent (E2)

* Exactly once per `action_request.idempotency_key` (A5). The FIRST thing it does is look the key up
  in `mbos.effector_calls` and replay the stored response. A replay never re-evaluates or re-acts.
* It sends ONLY the frozen draft in `payload.comms` (what Michael approved). It never re-plans or
  re-renders. No draft → blocked.
* A failed check → `status="blocked"`, recorded, with no simulated send. It does not raise, because
  raising would fail the workflow step. A-13: `finish_act` should map `status == "blocked"` to ACTION_FAILED.
* Consent: there is no consent ledger yet, so the check is recorded as `not_evaluated`. It does not
  block in dry-run, and `comms_spec.audit()` reports E2 as DRY_RUN_EXEMPT, never PASS. A live
  effector must treat `not_evaluated` as blocked.

The check results go in `effector_response["comms"]`, which the spine stores verbatim on the
ACTION_EXECUTED receipt. `audit()` reads them there, or from `details` once A-13 merges them.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Optional

import sqlalchemy as sa

import comms_spec as cs
from mbos.clock import iso, utcnow
from operator_ui import mbos_canonical

COMMS_PREFIXES = ("comms.", "offer.")  # offer.<channel>.send = a BINDING comms draft (category offer, step-up)
DncLookup = Callable[[str, str], tuple[Optional[datetime], Optional[bool], bool]]   # (ref, channel) → (scrubbed_at, listed, suppressed)
ConsentLookup = Callable[[str, str], dict]                                          # (ref, channel) → {"result", "reason", ...}


def _no_dnc_data(ref: str, channel: str):
    return None, None, False


def _no_consent_ledger(ref: str, channel: str) -> dict:
    return {"result": "not_evaluated", "reason": "no consent ledger yet (dry-run)"}


class CommsDryRunEffector:
    name = "comms-dry-run"
    dry_run = True
    version = "0.1.0"

    def __init__(self, clock: Callable[[], datetime] = utcnow, dnc_lookup: DncLookup = _no_dnc_data,
                 consent_lookup: ConsentLookup = _no_consent_ledger, fallback: Any = None):
        self.clock = clock
        self.dnc_lookup = dnc_lookup
        self.consent_lookup = consent_lookup
        self.fallback = fallback  # effector for non-comms capabilities (e.g. mbos.reference DryRunEffector)

    # ------------------------------------------------------------------ Effector protocol
    def execute(self, engine: sa.Engine, action_request: dict[str, Any]) -> dict[str, Any]:
        if self.dry_run is not True:
            raise RuntimeError("CommsDryRunEffector is dry-run only")
        if not action_request["capability"].startswith(COMMS_PREFIXES):
            if self.fallback is None:
                raise ValueError(f"{self.name} handles comms.* / offer.* only; no fallback for {action_request['capability']}")
            return self.fallback.execute(engine, action_request)
        key = action_request["idempotency_key"]
        with engine.begin() as conn:
            prior = conn.execute(sa.text("SELECT response FROM mbos.effector_calls WHERE idempotency_key = :k"),
                                 {"k": key}).one_or_none()
            if prior is not None:
                return prior.response  # exactly once: replay, never re-act
            response = self._evaluate(conn, action_request)
            row = conn.execute(sa.text(
                "INSERT INTO mbos.effector_calls (idempotency_key, action_request_id, capability, provider, "
                " provider_msg_id, dry_run, request, response) "
                "VALUES (:k, :a, :c, :p, :m, true, CAST(:req AS jsonb), CAST(:resp AS jsonb)) "
                "ON CONFLICT (idempotency_key) DO NOTHING RETURNING response"),
                {"k": key, "a": action_request["action_request_id"], "c": action_request["capability"],
                 "p": response["provider"], "m": response["provider_msg_id"],
                 "req": mbos_canonical.canonical_json(action_request["payload"]),
                 "resp": mbos_canonical.canonical_json(response)}).one_or_none()
            if row is None:  # lost a race with a concurrent call on the same key: return the winner's response
                row = conn.execute(sa.text("SELECT response FROM mbos.effector_calls WHERE idempotency_key = :k"),
                                   {"k": key}).one()
            return row.response

    # ------------------------------------------------------------------ checks
    def _evaluate(self, conn: sa.Connection, areq: dict[str, Any]) -> dict[str, Any]:
        now = self.clock()
        key = areq["idempotency_key"]
        channel = areq["capability"].split(".")[1] if areq["capability"].count(".") >= 2 else "?"
        c = (areq.get("payload") or {}).get("comms")
        blocked: list[str] = []
        block: dict[str, Any] = {"kind": "comms", "channel": channel, "evaluated_at": iso(now), "effector": f"{self.name}@{self.version}"}
        if not isinstance(c, dict):
            blocked.append("no comms draft in the approved payload (planner/A-13 missing); nothing to send")
            return self._response(key, channel, block, blocked)

        ref = (c.get("recipient") or {}).get("ref") or ""
        block.update(template_id=c.get("template_id"), template_version=c.get("template_version"),
                     template_hash=c.get("template_hash"), first_message=bool(c.get("first_message")),
                     binding=bool(c.get("binding")), delivery=c.get("delivery", "effector"), recipient_ref=ref)
        if c.get("channel") != channel:
            blocked.append(f"draft channel {c.get('channel')!r} != capability channel {channel!r}")
        is_offer_cap = areq["capability"].startswith("offer.")
        if block["binding"] and not is_offer_cap:
            blocked.append("binding draft under a non-offer capability (must be offer.<channel>.send: category offer, step-up)")
        if is_offer_cap and not block["binding"]:
            blocked.append("offer capability carrying a non-binding draft")

        # template integrity: the draft is recorded as conforming or not. A Michael-approved MODIFY may
        # differ, so it is not blocking, but the hash must name a real registry version.
        try:
            t = cs.get_template(c["template_id"], c["channel"], c["template_version"])
            hash_ok = t["content_hash"] == c["template_hash"] == cs.template_hash(t)
            rendered = cs.render(c["template_id"], c["channel"], c.get("variables") or {}, c["template_version"])
            block["template_conformant"] = hash_ok and rendered["body"] == c.get("body") and rendered["subject"] == c.get("subject")
            if not hash_ok:
                blocked.append("template_hash does not match the registry")
        except (KeyError, ValueError) as e:
            block["template_conformant"] = False
            blocked.append(f"template not in registry: {e}")

        # E1 disclosure
        reg = cs.load("templates")
        needed = reg["voice_disclosure"] if channel == "voice" else reg["disclosure"]
        block["disclosure_present"] = needed in (c.get("body") or "")
        if (block["first_message"] or channel == "voice") and not block["disclosure_present"]:
            blocked.append("first message / call without the AI disclosure (E1)")

        # E3 send window (recipient local time; unknown tz denies)
        win = cs.window_check(now, (c.get("recipient") or {}).get("tz"), channel)
        block["send_window_check"] = win
        if not win["ok"]:
            blocked.append(f"send window: {win['reason']}")

        # rate limits: our own prior simulated sends to this recipient on this channel
        rows = conn.execute(sa.text(
            "SELECT created_at, request->'comms'->'recipient'->>'ref' AS ref FROM mbos.effector_calls "
            "WHERE capability = :cap AND response->>'status' = 'simulated_send' AND created_at > :since"),
            {"cap": areq["capability"], "since": now - timedelta(days=7)}).all()
        history = [{"contact": r.ref, "channel": channel, "direction": "outbound", "at": r.created_at} for r in rows if r.ref]
        rate = cs.rate_check(history, ref, channel, now) if channel in cs.CHANNELS else {"ok": False, "reason": "unknown channel"}
        global_cap = cs.load("comms_policy")["rate_limits"]["global_per_day"].get(channel, 0)
        today = sum(1 for r in rows if now - r.created_at < timedelta(days=1))
        if rate["ok"] and today >= global_cap:
            rate = {"ok": False, "reason": f"global {channel} cap {global_cap}/day reached"}
        block["rate_limit_check"] = rate
        if not rate["ok"]:
            blocked.append(f"rate limit: {rate['reason']}")

        # DNC (fail closed for sms/voice) and internal suppression
        scrubbed_at, listed, suppressed = self.dnc_lookup(ref, channel)
        dnc = cs.dnc_check(scrubbed_at, listed, suppressed, channel, now)
        block["dnc_check"] = dnc
        if not dnc["ok"]:
            blocked.append(f"DNC: {dnc['reason']}")

        # E2 consent: recorded; not_evaluated only tolerated because this is dry-run
        consent = self.consent_lookup(ref, channel)
        block["consent_check"] = consent
        if consent.get("result") not in ("pass", "not_evaluated"):
            blocked.append(f"consent: {consent.get('reason', consent.get('result'))}")
        return self._response(key, channel, block, blocked)

    def _response(self, key: str, channel: str, block: dict, blocked: list[str]) -> dict[str, Any]:
        block["blocked_reasons"] = blocked
        status = "blocked" if blocked else "simulated_send"
        return {
            "provider": f"dry-run:comms-{channel}",
            "provider_msg_id": ("dry_" if not blocked else "blocked_") + mbos_canonical.sha256_of(key)[7:33],
            "status": status,
            "dry_run": True,
            "comms": block,
        }
