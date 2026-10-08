"""C-08: morning digest. A ranked "what to do first" list over scored Items.

``build_digest(items, as_of)`` is pure and deterministic: no clock (``as_of`` is passed in),
input order never matters, ties break on item_id. Agent 06's Operator UI renders it. Rows carry
data only; ``title`` is listing text and must be escaped by the renderer.

Order (explainable, lexicographic):
  1. bucket:  YES + alert  >  YES  >  MAYBE (research)  >  PASS flagged pass_on_priors (R13: research)
  2. inside a bucket: items with a deadline (recommendation.expires_at or normalized.ends_at) inside the
     horizon (default 72 h) first, soonest first
  3. then the C-19 ranking objective (ADR-0012): rank_score = risk-adjusted profit x confidence x
     capital velocity (x seasonality x cash pressure), highest first, so a quick small flip can outrank a
     big slow one. Every row names its components in ``reason``. A card scored before C-19 has no
     ``ranking``; it sorts after ranked rows in its bucket and says so.
  4. then time-to-cash, shortest first; then item_id

Excluded (listed with a reason, never silently dropped): archived PASS, past deadline, already decided
or closed states, items with no scorecard.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from . import __version__ as DIGEST_VERSION
from .canonical import content_hash, derived_ulid, parse_ts
from .numeric import D, fine, money

TOOL_NAME = "mbos_economics.digest"
OPEN_STATES = {"RESEARCHING", "SCORED", "RECOMMENDED", "AWAITING_APPROVAL", "HELD"}
_BUCKETS = {"act_alert": 0, "act": 1, "research": 2, "research_r13": 3}
_INF = Decimal("1e9")
_YES_TEXT = {"composite_ok": "composite", "confidence_ok": "low confidence (evidence)", "ev_pph_target_ok": "EV $/h below target",
             "class_ev_ok": "EV or cash multiple below the deal-class requirement", "remote_verification_ok": "remote verification",
             "sold_comps_ok": "sold comps", "fault_identified_ok": "repair fault not identified", "title_ok": "title"}


def _usd(x) -> str:
    return f"${D(x):,.2f}"


def _deadline(item: dict) -> str | None:
    cands = [t for t in ((item.get("recommendation") or {}).get("expires_at"),
                         (item.get("normalized") or {}).get("ends_at")) if t]
    return min(cands, key=lambda t: parse_ts(t)) if cands else None


def _row(item: dict, as_of: str, horizon: Decimal) -> tuple[dict | None, str | None]:
    iid = item.get("item_id")
    state = item.get("state")
    if state not in OPEN_STATES:
        return None, f"state {state}: already decided or closed"
    scores = item.get("scores")
    if not scores:
        return None, f"{state}: not scored yet (research gaps outstanding)"
    sc = scores["scorecard"]
    rec = item.get("recommendation") or {}
    d = sc["derived"]
    verdict = sc["decision"]
    if verdict == "PASS" and not sc.get("pass_on_priors"):
        return None, "PASS (evidence-backed): archive, no action"
    deadline = _deadline(item)
    hours_left = None
    if deadline:
        hours_left = fine(D((parse_ts(deadline) - parse_ts(as_of)).total_seconds()) / D(3600))
        if hours_left < 0:
            return None, f"deadline {deadline} has passed: re-score or archive"

    if verdict == "YES":
        bucket = "act_alert" if sc.get("alert") else "act"
        if sc["lane"] == "flip" and sc.get("walk_away_price") is not None:
            action = f"decide: offer at or below ${sc['walk_away_price']:,}"
        elif sc["lane"] == "service":
            action = "decide: send quote / confirm the job"
        else:
            action = "decide"
    elif verdict == "MAYBE":
        bucket = "research"
        hint = sc.get("cheapest_decisive_evidence")
        if hint:
            action = f"research: {hint}"
        elif sc.get("walk_away_price") is not None:
            action = f"negotiate: YES at or below ${sc['walk_away_price']:,}"
        elif sc.get("min_quote_for_yes") is not None:
            action = f"re-quote: YES at ${sc['min_quote_for_yes']:,} or more"
        else:
            blocked = [_YES_TEXT.get(k, k) for k, ok in sc.get("yes_conditions", {}).items() if not ok]
            action = "research: YES blocked by " + ", ".join(blocked)
    else:
        bucket = "research_r13"
        failed = [k for k, ok in sc.get("gates", {}).items() if not ok] or ["composite floor"]
        action = f"research before discarding (R13): PASS on {', '.join(failed)} rests on priors"

    ev_pph, conf = D(d["ev_profit_per_hour"]), D(d["confidence"])
    value = money(ev_pph * conf)
    ttc = D(d["time_to_cash_days"])
    rk = sc.get("ranking")
    parts = [verdict + (" + ALERT" if sc.get("alert") else "")]
    if rk and rk.get("timing_flag"):
        parts.append("WRONG BUY TODAY (out of season)")
    if rk:
        risk = ("no capital at risk" if D(d["cash_at_risk"]) <= 0 else f"{_usd(d['cash_at_risk'])} at risk")
        mult = f" ({d['cash_multiple']}x)" if d.get("cash_multiple") is not None else ""
        parts.append(f"{str(d.get('deal_class', '')).replace('_', ' ').lower()}: {risk}, back in {ttc} d{mult}")
        parts.append(f"rank {rk['rank_score']} = risk-adjusted {_usd(rk['risk_adjusted_profit'])} x conf "
                     f"{rk['confidence']} x velocity {rk['capital_velocity']}/day"
                     + (f" x season {rk['seasonality_factor_applied']}" if rk["seasonality_factor"] is not None else "")
                     + (f" x cash pressure {rk['cash_pressure_factor']}" if rk["cash_share_of_current_cash"] is not None else ""))
        parts.append(f"EV {_usd(ev_pph)}/h, EV {_usd(d['ev_decision'])}")
    else:
        parts += [f"EV {_usd(ev_pph)}/h x conf {conf} = {_usd(value)}/h", f"EV {_usd(d['ev_decision'])}",
                  f"cash in {ttc} d", "no capital-velocity ranking (scored before C-19: re-score)"]
    if hours_left is not None:
        parts.append(f"deadline in {hours_left} h")
    reason = "; ".join(parts) + f" -> {action}"
    in_window = hours_left is not None and hours_left <= horizon
    row = {
        "item_id": iid, "lane": sc["lane"], "category": item.get("category"),
        "title": (item.get("normalized") or {}).get("title"), "state": state,
        "verdict": verdict, "alert": bool(sc.get("alert")), "pass_on_priors": bool(sc.get("pass_on_priors")),
        "bucket": bucket, "action": action, "reason": reason,
        "value_per_hour": value, "rank_score": D(rk["rank_score"]) if rk else None,
        "deal_class": d.get("deal_class"), "capital_velocity": D(rk["capital_velocity"]) if rk else None,
        "cash_multiple": D(d["cash_multiple"]) if d.get("cash_multiple") is not None else None,
        "ranking": rk, "ev_profit_per_hour": ev_pph, "confidence": conf,
        "ev_decision": D(d["ev_decision"]), "time_to_cash_days": ttc,
        "deadline": deadline, "hours_left": hours_left,
        "window": "<24h" if in_window and hours_left <= 24 else ("<72h" if in_window else "later"),
        "refs": {"scorecard_id": scores["scorecard_id"], "inputs_hash": scores["inputs_hash"],
                 "recommendation_id": rec.get("recommendation_id"), "provenance_id": rec.get("provenance_id")},
        "_key": (_BUCKETS[bucket], 0 if in_window else 1, hours_left if in_window else _INF,
                1 if rk is None else 0, -D(rk["rank_score"]) if rk else -value, ttc, iid),
    }
    return row, None


def build_digest(items: list[dict], as_of: str, *, horizon_hours: int = 72, limit: int | None = None) -> dict:
    """Rank open, scored Items into a 'what to do first' list. Pure; writes nothing."""
    horizon = D(horizon_hours)
    rows, excluded = [], []
    for it in sorted(items, key=lambda i: str(i.get("item_id"))):
        row, why = _row(it, as_of, horizon)
        if row is None:
            excluded.append({"item_id": it.get("item_id"), "reason": why})
        else:
            rows.append(row)
    rows.sort(key=lambda r: r["_key"])
    shown = rows if limit is None else rows[:limit]
    out_rows = []
    for rank, r in enumerate(shown, 1):
        r = {k: v for k, v in r.items() if k != "_key"}
        r["rank"] = rank
        out_rows.append({k: (float(v) if isinstance(v, Decimal) else v) for k, v in r.items()})
    body = {"as_of": as_of, "horizon_hours": horizon_hours, "rows": out_rows, "excluded": excluded,
            "counts": {b: sum(1 for r in rows if r["bucket"] == b) for b in _BUCKETS}}
    digest_hash = content_hash(body)
    upstream = sorted({r["refs"]["provenance_id"] for r in out_rows if r["refs"]["provenance_id"]})
    prov_id = derived_ulid("prov", as_of, f"digest|{digest_hash}")
    provenance = {"provenance_id": prov_id, "created_at": as_of, "actor_type": "system",
                  "agent_name": "agent-03-economics", "basis": "INFERENCE", "tool_name": TOOL_NAME,
                  "tool_version": DIGEST_VERSION, "inputs_used": [{"ref": "digest", "hash": digest_hash}],
                  **({"derived_from": upstream} if upstream else {})}
    return {**body, "digest_hash": digest_hash, "provenance": provenance}


def render_text(digest: dict) -> str:
    """Plain-text daily summary (72-hour plan). The Operator UI does its own rendering."""
    lines = [f"MBOS morning digest, as of {digest['as_of']} (horizon {digest['horizon_hours']} h)"]
    for r in digest["rows"]:
        lines.append(f"{r['rank']:>2}. [{r['window']}] {r['category']}: {r['reason']}  ({r['item_id']})")
    if digest["excluded"]:
        lines.append(f"-- {len(digest['excluded'])} not listed: " +
                     "; ".join(f"{e['item_id']}: {e['reason']}" for e in digest["excluded"][:5])
                     + (" ..." if len(digest["excluded"]) > 5 else ""))
    return "\n".join(lines)
