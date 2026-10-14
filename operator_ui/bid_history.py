"""P1-01: auction history for items in My Bids. Each tracked bid record (market_prefs `bids[lot]`, the existing account-isolated
store) carries an APPEND-ONLY `observations` list: a new high bid, bid count, closing time or final price is a new entry, never an
edit of an earlier one. Connected evidence comes only from the existing receipt store (bid_state_watch.BidWatchStore), read-only.

What is recorded is what someone saw at one moment. Bids placed between two observations were not seen, so the history marks every
interval between observations as a gap and never invents the individual bids, their times or the bidders. Nothing here fetches a
source, signs in, polls or predicts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from html import escape as e
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
WINNING = ("winning", "bid placed")        # the owner's bid was leading (or had just been placed) when this was observed
CLASSES = {"MANUAL": "entered by you", "SNAPSHOT": "listing feed snapshot", "CONNECTED": "connected source evidence"}


def _when(v, field: str) -> str:
    """ISO date-time with an offset. A value without one (a datetime-local field) is America/Chicago, the owner's auction time."""
    s = str(v or "").strip()[:40]
    if not s:
        return ""
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as ex:
        raise ValueError(f"{field} must be a date and time like 2026-10-15T18:10") from ex
    return (t if t.tzinfo else t.replace(tzinfo=CT)).isoformat(timespec="seconds")


def _count(v):
    s = str(v or "").replace(",", "").strip()
    if not s:
        return None
    if not s.isdigit() or int(s) > 1_000_000:
        raise ValueError("bid count must be a whole number")
    return int(s)


def _obs_id(prev: str, body: dict) -> str:
    raw = json.dumps([prev, body], sort_keys=True, separators=(",", ":"))
    return "obs_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def baseline(rec: dict) -> list[dict]:
    """A record made before P1-01 has no observations. Its marking-time snapshot is shown (and, on the next entry, stored) as the first
    observation with the record's own provenance, so nothing it already said is lost."""
    if rec.get("bid") is None and rec.get("bidders") is None and not (rec.get("closes_at") or rec.get("closes")):
        return []
    prov = rec.get("provenance") if isinstance(rec.get("provenance"), dict) else {}
    snap = prov.get("kind") == "listing_snapshot"
    seen = str(rec.get("fetched_at") or prov.get("observed_at") or "") if snap else ""
    body = {"seq": 1, "recorded_at": rec.get("marked_at") or "", "observed_at": seen or rec.get("marked_at") or "",
            "observed_basis": "stated" if seen else "entry time",
            "high_bid": rec.get("bid"), "bid_count": None if rec.get("bidders") is None else int(rec["bidders"]),
            "closes_at": rec.get("closes_at") or rec.get("closes") or "", "status": "", "owner_max": rec.get("max_bid"), "final": False,
            "evidence_class": "SNAPSHOT" if snap else "MANUAL", "kind": "listing_snapshot" if snap else "owner_entry",
            "source": rec.get("source") or "", "note": "snapshot kept when the watch started", "source_account_access": "NONE"}
    return [{**body, "obs_id": _obs_id("", body)}]


def append(rec: dict, now: str, *, high_bid=None, bid_count=None, closes_at="", status="", owner_max=None, final=False,
           observed_at="", note="", kind="owner_entry", evidence_class="MANUAL") -> dict:
    """Add one observation to `rec` (mutated) and move the record's current fields to the latest observation. Earlier entries are
    never changed; an entry dated before the latest one is inserted into the timeline but does not replace the current values."""
    if high_bid is None and bid_count is None and not closes_at and not status:
        raise ValueError("enter at least a high bid, a bid count, a closing time or a status")
    if final and high_bid is None:
        raise ValueError("a verified final price needs the selling price")
    obs = rec.get("observations")
    if not isinstance(obs, list):
        obs = baseline(rec)
    body = {"seq": len(obs) + 1, "recorded_at": now, "observed_at": observed_at or now, "observed_basis": "stated" if observed_at else "entry time",
            "high_bid": high_bid, "bid_count": bid_count, "closes_at": closes_at, "status": status, "owner_max": owner_max, "final": bool(final),
            "evidence_class": evidence_class, "kind": kind, "source": rec.get("source") or "", "note": str(note or "").strip()[:200],
            "source_account_access": "NONE"}
    item = {**body, "obs_id": _obs_id(obs[-1]["obs_id"] if obs else "", body)}
    rec["observations"] = obs + [item]
    if owner_max is not None:
        rec["max_bid"] = owner_max
    if final:
        rec["final_price"], rec["final_verified_at"] = high_bid, item["observed_at"]
        if rec.get("status") not in ("won", "lost") and status not in ("won", "lost"):
            status = "closed"
    if timeline(rec)[-1]["obs_id"] == item["obs_id"]:           # the newest observation sets what My Bids shows as current
        if high_bid is not None:
            rec["bid"] = high_bid
        if bid_count is not None:
            rec["bidders"] = bid_count
        if closes_at:
            rec["closes_at"], rec["closes"] = closes_at, ""
        if status:
            rec["status"] = status
    return item


def _key(o: dict):
    try:
        t = datetime.fromisoformat(str(o.get("observed_at") or o.get("recorded_at") or "").replace("Z", "+00:00"))
        t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        t = datetime.max.replace(tzinfo=timezone.utc)
    return (t, o.get("evidence_class") != "CONNECTED", o.get("seq", 0))


def connected(lot: str, store=None) -> list[dict]:
    """Observations from the existing receipt store for this listing (an authenticated source e-mail or an authorized session).
    Read-only; empty when nothing is connected."""
    from . import bid_state_watch as bsw
    try:
        doc = (store or bsw.BidWatchStore()).load()
    except (OSError, ValueError):
        return []
    out = []
    for r in doc.get("receipts", []):
        d = r.get("details") or {}
        if r.get("listing_id") != lot or r.get("event") != "BID_NOTIFICATION_QUEUED":
            continue
        out.append({"seq": r.get("seq", 0), "obs_id": r.get("receipt_id", ""), "recorded_at": r.get("occurred_at", ""), "observed_at": r.get("occurred_at", ""),
                    "observed_basis": "stated", "high_bid": None if d.get("current_bid") is None else float(d["current_bid"]), "bid_count": None,
                    "closes_at": d.get("closes_at") or "", "status": {"WINNING": "winning", "OUTBID": "outbid", "ENDED_WON": "won", "ENDED_LOST": "lost"}.get(d.get("state"), ""),
                    "owner_max": None, "final": False, "evidence_class": "CONNECTED", "kind": (r.get("evidence") or {}).get("kind", ""),
                    "source": "", "note": f"receipt {r.get('receipt_id', '')}", "source_account_access": "NONE"})
    return out


def timeline(rec: dict, extra=()) -> list[dict]:
    obs = rec.get("observations") if isinstance(rec.get("observations"), list) else baseline(rec)
    return sorted([*obs, *extra], key=_key)


def summary(rec: dict, rows: list[dict]) -> dict:
    bids = [o for o in rows if o.get("high_bid") is not None]
    closes = [o["closes_at"] for o in rows if o.get("closes_at")]
    final = next((o for o in reversed(rows) if o.get("final")), None)
    last_mine = next((o for o in reversed(bids) if o.get("status") in WINNING), None)
    end_price = final["high_bid"] if final else (bids[-1]["high_bid"] if bids else None)
    return {"first_close": closes[0] if closes else "", "last_close": closes[-1] if closes else "",
            "final": final, "end_price": end_price, "last_mine": last_mine,
            "after_mine": None if last_mine is None or end_price is None else end_price - last_mine["high_bid"],
            "observed_change": None if len(bids) < 2 else bids[-1]["high_bid"] - bids[0]["high_bid"]}


def _money(v) -> str:
    return "UNKNOWN" if v is None else f"${v:,.0f}" if float(v).is_integer() else f"${v:,.2f}"


def _delta(v, unit="$") -> str:
    if v is None:
        return ""
    if v == 0:
        return "no change"
    sign = "+" if v >= 0 else "−"
    return f"{sign}${abs(v):,.0f}" if unit == "$" else f"{sign}{abs(v):g} bid{'' if abs(v) == 1 else 's'}"


def _ct(s: str) -> str:
    if not s:
        return "UNKNOWN"
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return e(s[:25])
    t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return t.astimezone(CT).strftime("%b %-d, %-I:%M %p CT")


def _span(a: str, b: str) -> str:
    try:
        s = int((datetime.fromisoformat(b.replace("Z", "+00:00")) - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds())
    except (ValueError, TypeError):
        return ""
    if s < 60:
        return f"{s}s"
    return f"{s // 3600}h {s % 3600 // 60}m" if s >= 3600 else f"{s // 60}m"


def _gap(a: dict, b: dict) -> str:
    parts = []
    pa, pb = a.get("high_bid"), b.get("high_bid")
    if pa is not None and pb is not None and pa != pb:
        parts.append(f"high bid {_delta(pb - pa)}")
    ca, cb = a.get("bid_count"), b.get("bid_count")
    if ca is not None and cb is not None and ca != cb:
        parts.append(_delta(cb - ca, "bids"))
    stated = a.get("observed_basis") == "stated" and b.get("observed_basis") == "stated"
    span = _span(a["observed_at"], b["observed_at"]) if stated else ""
    what = ("; ".join(parts) + ". ") if parts else ""
    return (f"<li class='bid-gap' data-gap='1'><span class='badge'>GAP</span> Not observed between these entries"
            f"{' (' + span + ')' if span else ' (time between not known)'}. {e(what)}Individual bids, their times and bidders in this gap were not recorded.</li>")


def _close_change(prev: str, now: str) -> str:
    if not prev or not now or prev == now:
        return ""
    try:
        d = (datetime.fromisoformat(now.replace("Z", "+00:00")) - datetime.fromisoformat(prev.replace("Z", "+00:00"))).total_seconds()
    except ValueError:
        return ""
    word = "extended" if d > 0 else "moved earlier"
    return f" · <b class='bid-close-change'>closing {word} {_span(prev, now) if d > 0 else _span(now, prev)}: {_ct(prev)} → {_ct(now)}</b>"


def render(lot: str, rec: dict, tok, return_to: str = "", store=None) -> str:
    rows = timeline(rec, connected(lot, store))
    s = summary(rec, rows)
    final = s["final"]
    head = (f"<dl class='bid-hist-sum small'>"
            f"<div><dt>Item</dt><dd>{e(rec.get('title') or lot)}</dd></div><div><dt>Location</dt><dd>{e(rec.get('location') or 'UNKNOWN')}</dd></div>"
            f"<div><dt>Your max bid</dt><dd>{_money(rec.get('max_bid'))}</dd></div>"
            f"<div><dt>Original closing</dt><dd>{_ct(s['first_close'])}</dd></div>"
            f"<div><dt>Revised closing</dt><dd>{_ct(s['last_close']) if s['last_close'] != s['first_close'] else 'no change observed'}</dd></div>"
            f"<div><dt>Final price</dt><dd data-final='{'' if not final else final['high_bid']}'>{(_money(final['high_bid']) + ' (verified, ' + CLASSES[final['evidence_class']] + ')') if final else 'not verified yet'}</dd></div>"
            f"<div><dt>Change after your last bid</dt><dd data-after-mine='{'' if s['after_mine'] is None else s['after_mine']}'>"
            + (f"{_delta(s['after_mine'])} (from {_money(s['last_mine']['high_bid'])} while you led to {_money(s['end_price'])}{' final' if final else ' last seen'})"
               if s["after_mine"] is not None else "UNKNOWN (no observation while your bid was leading)") + "</dd></div></dl>")
    li, prev, prev_close = [], None, ""
    for o in rows:
        if prev is not None:
            li.append(_gap(prev, o))
        chg = ""
        if prev is not None and prev.get("high_bid") is not None and o.get("high_bid") is not None:
            chg = f" ({_delta(o['high_bid'] - prev['high_bid'])})"
        cnt = "" if o.get("bid_count") is None else f" · {o['bid_count']} bids" + (
            f" ({_delta(o['bid_count'] - prev['bid_count'], 'bids')})" if prev is not None and prev.get("bid_count") is not None else "")
        when = _ct(o["observed_at"]) + ("" if o.get("observed_basis") == "stated" else " <span class='mut'>(time you entered it; the moment seen was not stated)</span>")
        cls = o.get("evidence_class") if o.get("evidence_class") in CLASSES else "MANUAL"
        close = (f" · closes {_ct(o['closes_at'])}" + _close_change(prev_close, o["closes_at"])) if o.get("closes_at") else ""
        li.append(f"<li class='bid-obs' data-obs='{e(o['obs_id'])}' data-class='{cls}'><b>{when}</b><br>"
                  f"{'<b>FINAL PRICE (verified)</b> ' if o.get('final') else ''}high bid <b>{_money(o.get('high_bid'))}</b>{chg}{cnt}"
                  f"{' · ' + e(o['status']) if o.get('status') else ''}{' · your max ' + _money(o['owner_max']) if o.get('owner_max') is not None else ''}{close}<br>"
                  f"<span class='badge bid-ev'>{cls}</span> <span class='mut'>{CLASSES[cls]}{' · ' + e(o['note']) if o.get('note') else ''} · recorded {_ct(o.get('recorded_at') or '')}</span></li>")
        prev = o
        prev_close = o.get("closes_at") or prev_close
    body = (f"<ul class='bid-hist'>{''.join(li)}</ul>" if li else "<p class='small mut'>No observations yet.</p>")
    back = f"<input type='hidden' name='return_to' value='{e(return_to)}'>" if return_to else ""
    form = (f"<details class='small bid-observe'><summary>Add an observation (what you saw on the auction)</summary>"
            f"<form method='post' action='/market/bid' class='bid-obs-form'>{tok()}{back}<input type='hidden' name='lot' value='{e(lot)}'>"
            "<label>High bid $ <input name='high_bid' size='7' inputmode='decimal'></label> "
            "<label>Bid count <input name='bid_count' size='5' inputmode='numeric'></label> "
            "<label>Status <select name='status'><option value=''>not noted</option>"
            + "".join(f"<option value='{s}'>{s}</option>" for s in ("watching", "bid placed", "winning", "outbid", "won", "lost", "closed")) + "</select></label> "
            "<label>Closing (Central) <input name='closes_at' type='datetime-local'></label> "
            "<label>Seen at (Central, optional) <input name='observed_at' type='datetime-local'></label> "
            "<label>Your max $ <input name='owner_max' size='7' inputmode='decimal'></label> "
            f"<label>Location <input name='location' maxlength='80' value='{e(rec.get('location') or '')}'></label> "
            "<label>Where you saw it <input name='note' maxlength='200' placeholder='e.g. HiBid lot page'></label> "
            "<label class='bid-final'><input type='checkbox' name='final' value='1'> This is the final selling price, checked on the source</label>"
            "<button name='act' value='observe'>Add observation</button></form></details>")
    return (f"<details class='bid-history' data-history='{e(lot)}'><summary>History ({len(rows)} observation{'' if len(rows) == 1 else 's'})</summary>"
            f"{head}{body}<p class='small mut'>Earlier entries are never changed. Gaps mean nobody observed the auction in between.</p>{form}</details>")
