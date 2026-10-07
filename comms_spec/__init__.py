"""Communications dry-run spec as data (task F-03). Stdlib only. NOTHING HERE SENDS.

Data (versioned JSON in `data/`):
  templates.v1.json             template registry: versions, content hashes, binding flags, approval status
  qa_sets.v1.json               seller Q&A per flip category, intake per service category
  comms_policy.v1.json          send window, rate limits, consent, DNC, opt-out, escalation triggers
  acceptance_thresholds.v1.json E1-E7 pass/fail thresholds

Functions are pure checks that a future effector (and the planner) call BEFORE proposing or executing
a send. Each returns a decision plus reasons, so the result can be written into a receipt's
`details.kind=comms` block. They never raise for a "no"; they raise only on bad input.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from operator_ui import mbos_canonical  # vendored ADR-0010 reference (byte-identical)

DATA = Path(__file__).resolve().parent / "data"
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
CHANNELS = ("sms", "email", "voice")
HASHED_FIELDS = ("template_id", "version", "channel", "subject", "body", "binding", "commercial")


@lru_cache(maxsize=None)
def load(name: str) -> dict:
    return json.loads((DATA / f"{name}.v1.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- templates
def template_hash(t: dict) -> str:
    return mbos_canonical.sha256_of({k: t.get(k) for k in HASHED_FIELDS})


def placeholders(t: dict) -> set[str]:
    return set(_PLACEHOLDER.findall((t.get("subject") or "") + "\n" + t["body"]))


def get_template(template_id: str, channel: str, version: Optional[int] = None) -> dict:
    found = [t for t in load("templates")["templates"] if t["template_id"] == template_id and t["channel"] == channel
             and (version is None or t["version"] == version)]
    if not found:
        raise KeyError(f"no template {template_id!r} for channel {channel!r} (version {version})")
    return max(found, key=lambda t: t["version"])


def render(template_id: str, channel: str, variables: dict[str, Any], version: Optional[int] = None) -> dict:
    """Render a DRAFT payload for an ActionRequest. Does not send. Refuses missing variables, and
    supplies the disclosure texts itself so they cannot be omitted or altered by a caller."""
    reg = load("templates")
    t = get_template(template_id, channel, version)
    if template_hash(t) != t["content_hash"]:
        raise ValueError(f"{template_id} v{t['version']} content_hash mismatch: the registry was edited without rehash")
    fixed = {"disclosure": reg["disclosure"], "voice_disclosure": reg["voice_disclosure"]}
    clash = set(variables) & set(fixed)
    if clash:
        raise ValueError(f"callers may not supply {sorted(clash)}")
    values = {**{k: str(v) for k, v in variables.items()}, **fixed}
    missing = placeholders(t) - set(values)
    if missing:
        raise ValueError(f"missing template variables: {sorted(missing)}")
    sub = lambda s: _PLACEHOLDER.sub(lambda m: values[m.group(1)], s) if s else s  # noqa: E731
    return {
        "template_id": t["template_id"], "template_version": t["version"], "template_hash": t["content_hash"],
        "channel": channel, "subject": sub(t.get("subject")), "body": sub(t["body"]),
        "binding": t["binding"], "commercial": t["commercial"],
        "template_approval": t["approval"]["status"],
    }


def action_constraints(rendered: dict) -> dict:
    """ActionRequest fields a rendered template forces (binding => tier 0, irreversible, step-up)."""
    if rendered["binding"]:
        return {**load("comms_policy")["binding_rules"]["binding_templates_force"], "category": "offer"}
    return {"tier": 0, "reversibility": "irreversible", "step_up": False,
            "category": {"sms": "sms", "email": "email", "voice": "phone_call"}[rendered["channel"]]}


# ---------------------------------------------------------------- Q&A
def questions(lane: str, category: str) -> list[dict]:
    qa = load("qa_sets")
    common, specific = (qa["flip_common"], qa["flip"]) if lane == "flip" else (qa["service_common"], qa["service"])
    if category not in specific:
        raise KeyError(f"no Q&A set for {lane}/{category}")
    return specific[category] + common


# ---------------------------------------------------------------- send window (E3)
def window_check(send_at_utc: datetime, recipient_tz: Optional[str], channel: str,
                 last_inbound_at_utc: Optional[datetime] = None) -> dict:
    pol = load("comms_policy")["send_window"]
    if not recipient_tz:
        return {"ok": False, "reason": "recipient timezone unknown (policy: deny)"}
    try:
        local = send_at_utc.astimezone(ZoneInfo(recipient_tz))
    except Exception:  # noqa: BLE001
        return {"ok": False, "reason": f"unknown timezone {recipient_tz!r} (policy: deny)"}
    ex = pol["reply_exemption"]
    if (channel in ex["applies_to"] and last_inbound_at_utc is not None
            and timedelta(0) <= send_at_utc - last_inbound_at_utc <= timedelta(minutes=ex["within_minutes_of_inbound"])):
        return {"ok": True, "reason": "reply exemption (counterparty wrote within the last hour)", "local": local.isoformat()}
    if local.strftime("%A").lower() in pol["no_outbound_days"]:
        return {"ok": False, "reason": f"no outbound on {local.strftime('%A')}", "local": local.isoformat()}
    start, end = pol["effective"]["start"], pol["effective"]["end"]
    hm = local.strftime("%H:%M")
    if not (start <= hm < end):
        return {"ok": False, "reason": f"outside {start}-{end} recipient local time ({hm})", "local": local.isoformat()}
    return {"ok": True, "reason": "inside send window", "local": local.isoformat()}


# ---------------------------------------------------------------- rate limits
def rate_check(history: Iterable[dict], contact: str, channel: str, now_utc: datetime) -> dict:
    """history: past OUTBOUND sends and INBOUND messages {contact, channel, direction, at (datetime)}."""
    pol = load("comms_policy")["rate_limits"]
    h = [m for m in history if m["contact"] == contact]
    out = [m for m in h if m["direction"] == "outbound" and m["channel"] == channel]
    day = [m for m in out if now_utc - m["at"] < timedelta(days=1)]
    week = [m for m in out if now_utc - m["at"] < timedelta(days=7)]
    replied_24h = any(m["direction"] == "inbound" and now_utc - m["at"] < timedelta(days=1) for m in h)
    replied_7d = any(m["direction"] == "inbound" and now_utc - m["at"] < timedelta(days=7) for m in h)
    lim = pol["per_contact"][channel]
    if channel == "voice":
        if len(day) >= lim["max_attempts_per_day"]:
            return {"ok": False, "reason": "voice: max attempts per day reached"}
        if len(week) >= lim["max_attempts_per_7_days"]:
            return {"ok": False, "reason": "voice: max attempts per 7 days reached"}
        return {"ok": True, "reason": "within voice limits"}
    cap = lim["max_per_day_active_thread"] if replied_24h else lim["max_per_day"]
    if len(day) >= cap:
        return {"ok": False, "reason": f"{channel}: {len(day)} sent today (cap {cap})"}
    if not replied_7d and len(week) >= lim["max_per_7_days_without_reply"]:
        return {"ok": False, "reason": f"{channel}: {len(week)} unanswered in 7 days (cap {lim['max_per_7_days_without_reply']})"}
    return {"ok": True, "reason": "within rate limits"}


# ---------------------------------------------------------------- opt-out (E4)
def is_opt_out(text: str) -> bool:
    norm = re.sub(r"[^\w ]", "", (text or "").strip()).strip().upper()
    norm = re.sub(r"\s+", " ", norm)
    return norm in {k.upper() for k in load("comms_policy")["opt_out"]["keywords"]}


def dnc_check(last_scrub_utc: Optional[datetime], on_national_dnc: Optional[bool], suppressed: bool,
              channel: str, now_utc: datetime) -> dict:
    d = load("comms_policy")["dnc"]
    if suppressed:
        return {"ok": False, "result": "suppressed", "reason": "contact opted out (internal suppression)"}
    if channel not in d["applies_to"]:
        return {"ok": True, "result": "not_applicable", "reason": f"DNC registry does not apply to {channel}"}
    if last_scrub_utc is None or on_national_dnc is None:
        return {"ok": False, "result": "unknown", "reason": "no DNC scrub on record (fail closed)"}
    if now_utc - last_scrub_utc > timedelta(days=d["national_registry_scrub_max_age_days"]):
        return {"ok": False, "result": "stale", "reason": f"DNC scrub older than {d['national_registry_scrub_max_age_days']} days"}
    if on_national_dnc:
        return {"ok": False, "result": "listed", "reason": "number is on the National DNC Registry"}
    return {"ok": True, "result": "clear", "reason": "scrubbed within 31 days; not listed"}


# ---------------------------------------------------------------- E1-E7 audit over receipts
def audit(receipts: list[dict], stop_events: Iterable[dict] = ()) -> dict:
    """Evaluate the testable E-thresholds on Receipt v1 docs (details.kind=comms) and STOP events
    {contact, stop_at, suppressed_at, sends_after}. Dry-run 'not_evaluated' checks are reported as
    DRY_RUN_EXEMPT, never as PASS."""
    thr = load("acceptance_thresholds")["tests"]
    # A comms receipt's check block sits in `details` (once A-13 merges it) or in `effector_response.comms`
    # (F-06 effector, today). Blocked attempts are recorded but are NOT sends.
    sends, blocked = [], []
    for r in receipts:
        if r.get("type") != "ACTION_EXECUTED":
            continue
        d = r.get("details") or {}
        block = d if "channel" in d else (r.get("effector_response") or {}).get("comms")
        if not block or block.get("kind", d.get("kind")) != "comms":
            continue
        rr = {**r, "details": {**d, **block, "kind": "comms"}}
        (blocked if (r.get("effector_response") or {}).get("status") == "blocked" else sends).append(rr)
    out: dict[str, Any] = {"sends": len(sends), "blocked": len(blocked)}

    first = [r for r in sends if r["details"].get("first_message") or r["details"].get("channel") == "voice"]
    disclosed = [r for r in first if r["details"].get("disclosure_present") is True]
    out["E1"] = _ratio(len(disclosed), len(first), thr["E1"]["pass"]["min_ratio"])

    checks = [(r["details"].get("consent_check") or {}, r["details"].get("dnc_check") or {}) for r in sends]
    recorded = [c.get("result") not in (None, "not_evaluated") and d.get("result") not in (None, "not_evaluated")
                for c, d in checks]
    exempt = [c.get("result") == "not_evaluated" and r["effector_response"].get("dry_run") is True
              for (c, _), r in zip(checks, sends)]
    if checks and not all(recorded) and all(rec or ex for rec, ex in zip(recorded, exempt)):
        out["E2"] = {"status": "DRY_RUN_EXEMPT", "n": len(sends), "exempt": sum(exempt)}
    else:
        out["E2"] = _ratio(sum(recorded), len(sends), thr["E2"]["pass"]["min_ratio"])

    bad = [r["receipt_id"] for r in sends if (r["details"].get("send_window_check") or {}).get("ok") is False]
    out["E3"] = {"status": "PASS" if not bad else "FAIL", "violations": bad}

    stops = list(stop_events)
    late = [s for s in stops if (s["suppressed_at"] - s["stop_at"]).total_seconds() > thr["E4"]["pass"]["max_seconds_p100"]]
    after = sum(s.get("sends_after", 0) for s in stops)
    out["E4"] = {"status": "PASS" if not late and after <= thr["E4"]["pass"]["max_sends_after_stop"] else "FAIL",
                 "late": len(late), "sends_after_stop": after, "n": len(stops)}

    out["E5"] = {"status": "NOT_TESTABLE_IN_DRY_RUN", "reason": thr["E5"]["basis"]}

    with_id = [r for r in sends if (r.get("effector_response") or {}).get("provider_msg_id")]
    out["E6"] = _ratio(len(with_id), len(sends), thr["E6"]["pass"]["min_ratio"])

    binding_unapproved = [r["receipt_id"] for r in sends if r["details"].get("binding") and not r.get("approval_id")]
    out["E7"] = {"status": "PASS" if not binding_unapproved else "FAIL", "binding_without_approval": binding_unapproved}
    return out


def _ratio(ok: int, n: int, need: float) -> dict:
    if n == 0:
        return {"status": "NO_DATA", "n": 0}
    return {"status": "PASS" if ok / n >= need else "FAIL", "ratio": round(ok / n, 4), "n": n}


# ---------------------------------------------------------------- maintenance
def rehash(path: Path = DATA / "templates.v1.json") -> int:
    """Recompute content_hash for every template (run after editing; bump `version` for any content change)."""
    reg = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for t in reg["templates"]:
        h = template_hash(t)
        if t.get("content_hash") != h:
            t["content_hash"], changed = h, changed + 1
    path.write_text(json.dumps(reg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    load.cache_clear()
    return changed
