"""F-155: 'DealSniffer Suggestions' for /market. Display only: no bid, no contact, no spend.

Every number comes from the lane 03 engine (`mbos_economics`: estimate_item -> score_item, the same scorer path the opportunity card
reads); this module only builds an Item from a lot, applies the owner's rules and labels every input. No new engine, nothing guessed.
Owner rules (his stated needs): about $500 cap per purchase; little or no repair; his own resale target (prefs `resale_targets`,
lot id -> USD) replaces the engine's resale. Auction EVENTS (no price) are never ranked. A lot with too many unknowns goes below the
ranking as 'needs research' and is never ranked on a guessed number. Pallet/wholesale lots are shown with labelled estimates only."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

import html

CAP = 500.0
REPAIR_MAX = 50.0                 # "little or no repair": engine parts+materials above this is outside the owner's rule unless MBOS_SUGGEST_REPAIR_MAX raises it
TOP_N = 10
ROAD_FACTOR = 1.25                # straight-line miles -> road miles: an ESTIMATE, labelled as one
CATS = (("trailer", "trailer"), ("mower", "mower"), ("generator", "generator"), ("welder", "welder"), ("compressor", "compressor"),
        ("forklift", "commercial_equipment"), ("pallet jack", "commercial_equipment"), ("tool", "tool"), ("saw", "tool"), ("drill", "tool"))
PALLET = re.compile(r"\b(pallets?|wholesale|liquidation|truckload|bulk lot|case lot)\b", re.I)
UNITS = re.compile(r"\b(\d{1,5})\s*(?:pcs|pieces|units|items|count|ct)\b", re.I)


e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731


def _cap() -> float:
    try:
        return float(os.environ.get("MBOS_SUGGEST_CAP_USD") or CAP)
    except ValueError:
        return CAP


def _repair_max() -> float:
    try:
        return float(os.environ.get("MBOS_SUGGEST_REPAIR_MAX") or REPAIR_MAX)
    except ValueError:
        return REPAIR_MAX


def is_event(c: dict) -> bool:
    return bool(c.get("event")) or "event" in str(c.get("kind") or "")


def is_pallet(c: dict) -> bool:
    return bool(PALLET.search(f"{c.get('title') or ''} {c.get('category') or ''}"))


def engine_category(c: dict) -> str | None:
    t = f"{c.get('title') or ''} {c.get('category') or ''}".lower()
    return next((v for k, v in CATS if re.search(rf"\b{k}s?\b", t)), None)


def _item(c: dict, cat: str, asof: str) -> dict:
    from mbos_economics.canonical import derived_ulid
    pid = derived_ulid("prov", asof, f"market|{c['id']}")
    loc = {"city": (c.get("city") or "").split(",")[0] or None, "state": c.get("state")}
    if c.get("distance") is not None:
        loc["road_miles_one_way"] = round(c["distance"] * ROAD_FACTOR, 1)
    return {"item_id": f"market:{c['id']}", "type": "flip", "category": cat, "sources": [{"provenance_id": pid, "first_seen_at": asof}],
            "research": [], "normalized": {"title": str(c.get("title") or "")[:200], "condition": c.get("condition") or "unknown",
                                           "price": {"amount": c["bid"], "currency": "USD", "type": "auction_current"}, "location": {k: v for k, v in loc.items() if v is not None}}}


def _label(v, basis: str, note: str = "") -> dict:
    return {"value": v, "basis": basis, "note": note}


def score_lot(c: dict, owner_target: float | None, asof: str) -> dict:
    """-> {'numbers': {...labelled...}} or {'unknown': [reasons]}. Only the engine produces numbers."""
    from mbos_economics.config import load_config
    from mbos_economics.engine import score_item
    from mbos_economics.estimate import apply_estimate, estimate_item
    from mbos_economics.canonical import derived_ulid
    cat = engine_category(c)
    miss = []
    if cat is None:
        miss.append("category the engine has no estimate for")
    if c.get("bid") is None:
        miss.append("no current/opening bid (price unknown)")
    if c.get("distance") is None:
        miss.append("distance unknown (location not found)")
    if owner_target is None:
        miss.append("no sold-price evidence on file and no owner resale target (the engine never guesses resale)")
    if miss:
        return {"unknown": miss}
    cfg = load_config()
    item = _item(c, cat, asof)
    pid = derived_ulid("prov", asof, f"owner-target|{c['id']}")
    comp = {"kind": "sold", "price": owner_target, "sold_date": asof[:10], "provenance_id": pid, "source": "owner-set resale target (not a sold sale)"}
    over = {f"resale.{k}": {"value": owner_target, "basis": "FACT", "provenance_id": pid, "human_attested": True, "note": "owner-set resale target"}
            for k in ("target_sell_price", "comp_price_expected")}
    est = estimate_item(item, {"comps": [comp], "overrides": over}, asof, scoring_cfg=cfg)
    if est["status"] != "estimated":
        return {"unknown": [g["detail"] for g in est["gaps"] if g["blocking"]] or ["the engine could not estimate this lot"]}
    it = apply_estimate(item, est)
    sc = score_item(it, cfg, asof)
    card = sc["scores"]["scorecard"]
    d, econ = card["derived"], it["economics"]
    ceiling, ceil_basis = card.get("walk_away_price"), "engine walk-away (YES level)"
    if ceiling is None:                  # YES needs more sold comps than an owner target gives; use the engine's own bisect for the highest bid it does not call PASS
        from mbos_economics.engine import _bisect_int, _with, compute
        from mbos_economics.inputs import build_engine_input
        inp = build_engine_input(it)
        ceiling = _bisect_int(0, int(owner_target), lambda a: compute(_with(inp, lambda e: e["acquisition"].__setitem__("expected_buy_price", a)), cfg)["decision"] != "PASS", want_max=True)
        ceil_basis = "engine ceiling: highest bid it does not score PASS (MAYBE level; YES needs more sold comps)"
    rehab = econ["rehab"]
    repair = float(rehab.get("parts_cost") or 0) + float(rehab.get("materials_cost") or 0)
    return {"numbers": {
        "walk_away": ceiling, "ceiling_basis": ceil_basis, "repair": repair, "repair_known": bool(rehab.get("repair_scope_known")),
        "resale_low": econ["resale"].get("comp_price_low"), "resale_likely": econ["resale"].get("comp_price_expected"),
        "resale_high": econ["resale"].get("comp_price_high"), "net": d.get("net_profit_deterministic"), "ev_net": d.get("ev_net_profit"),
        "days": d.get("time_to_cash_days"), "velocity": d.get("capital_velocity"), "verdict": sc["recommendation"]["verdict"],
        "reasons": list(sc["recommendation"].get("rationale") or [])[:3], "assumed": [a for a in (econ.get("estimates_meta") or {}).get("assumptions", [])][:6]}}


def suggest(cards: list[dict], prefs: dict | None = None, asof: str | None = None, n: int = TOP_N) -> dict:
    asof = asof or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    targets = (prefs or {}).get("resale_targets") if isinstance((prefs or {}).get("resale_targets"), dict) else {}
    cap, rmax = _cap(), _repair_max()
    out = {"ranked": [], "research": [], "outside": [], "pallets": [], "events": 0, "cap": cap, "repair_max": rmax}
    for c in cards:
        if c.get("fixture"):             # a fixture is never a current listing
            continue
        if is_event(c):
            out["events"] += 1
            continue
        if is_pallet(c):
            out["pallets"].append(c)
            continue
        t = targets.get(c["id"])
        t = float(t) if isinstance(t, (int, float)) and not isinstance(t, bool) and 0 < t < 10**7 else None
        try:
            r = score_lot(c, t, asof)
        except Exception as ex:  # noqa: BLE001  one lot never breaks the page
            r = {"unknown": [f"the engine could not score this lot ({type(ex).__name__})"]}
        row = {"card": c, "owner_target": t, **r}
        if "unknown" in r:
            out["research"].append(row)
            continue
        x = r["numbers"]
        ceiling = x["walk_away"]
        why = []
        if ceiling is None:
            why.append("the engine finds no bid price at which this lot is not a PASS")
        elif ceiling < (c["bid"] or 0):
            why.append(f"the current bid ${c['bid']:,.0f} is already above the engine's walk-away ${ceiling:,}")
        if (c["bid"] or 0) > cap:
            why.append("the current bid is over your per-purchase cap (owner SETTING)")
        if x["repair"] > rmax:
            why.append(f"the engine's repair allowance ${x['repair']:,.0f} is over your 'little or no repair' rule (${rmax:,.0f})")
        if (x["ev_net"] or 0) <= 0:
            why.append("the engine's expected profit is not positive")
        row["max_bid"] = None if ceiling is None else min(float(ceiling), cap)
        if why:
            out["outside"].append({**row, "why_not": why})
        else:
            out["ranked"].append(row)
    out["ranked"].sort(key=lambda r: (-(r["numbers"]["velocity"] or 0), r["card"]["title"]))   # the engine's capital velocity (ADR-0012)
    out["ranked"] = out["ranked"][:n]
    return out


def _capl(cap: float) -> str:
    """The cap is a labelled owner SETTING (F-51: never an unlabelled $500 on /market)."""
    return f"<span class='sg-setting'>${cap:,.0f} cap (owner SETTING, not your cash)</span>"


def _m(v) -> str:
    return "UNKNOWN" if v is None else f"${float(v):,.0f}"


def _tag(basis: str) -> str:
    return f" <span class='tag'>{e(basis)}</span>"


def render_ranked(r: dict) -> str:
    c, x = r["card"], r["numbers"]
    days = "UNKNOWN" if x["days"] is None else f"{x['days']:g} days"
    tgt = r["owner_target"]
    resale = (f"owner target {_m(tgt)}{_tag('OWNER-SET')} (overrides the engine)" if tgt is not None else "")
    rng = f"low {_m(x['resale_low'])} / likely {_m(x['resale_likely'])} / optimistic {_m(x['resale_high'])}"
    link = f" <a href='{e(c['url'])}' rel='noopener noreferrer' target='_blank'>Original listing</a>" if c.get("url") else ""
    dist = f"{c['distance']:.0f} mi{_tag('ESTIMATE: straight-line, from the cached location')}" if c.get("distance") is not None else "distance UNKNOWN"
    return ("<li class='card sg-row'>"
            f"<b>{e(c['title'])}</b> <span class='mut small'>{e(c.get('source') or '')}</span>{link}<table>"
            f"<tr><th>Max bid (engine walk-away, capped at {_capl(_cap())})</th><td>{_m(r['max_bid'])}{_tag('ENGINE')} <span class='small mut'>{e(x['ceiling_basis'])}</span></td></tr>"
            f"<tr><th>Repair allowance</th><td>{_m(x['repair'])}{_tag('ESTIMATE' if not x['repair_known'] else 'ENGINE')} {'category prior, not a diagnosis' if not x['repair_known'] else ''}</td></tr>"
            f"<tr><th>Resale</th><td>{resale or rng}{_tag('OWNER-SET' if tgt is not None else 'ENGINE')}"
            f"{'<br><span class=small>engine range: ' + rng + '</span>' if tgt is not None else ''}</td></tr>"
            f"<tr><th>Net profit if it goes as planned</th><td>{_m(x['net'])}{_tag('ESTIMATE')} (probability-weighted {_m(x['ev_net'])})</td></tr>"
            f"<tr><th>Time to cash</th><td>{days}{_tag('ESTIMATE')}</td></tr>"
            f"<tr><th>Distance</th><td>{dist}</td></tr>"
            f"<tr><th>Why</th><td>{e('; '.join(x['reasons']) or 'engine verdict ' + str(x['verdict']))}</td></tr></table>"
            + (f"<p class='small mut'>Inputs the engine assumed: {e('; '.join(str(a.get('field', '')) + ' (' + str(a.get('basis', '')) + ')' for a in x['assumed']))}</p>" if x["assumed"] else "")
            + "</li>")


def render_pallet(c: dict) -> str:
    u = UNITS.search(c.get("title") or "")
    unk = lambda what: f"<tr><th>{what}</th><td>UNKNOWN{_tag('not estimated')}</td></tr>"  # noqa: E731
    return (f"<li class='card sg-row'><b>{e(c['title'])}</b><table>"
            f"<tr><th>Pallet price</th><td>{_m(c.get('bid'))}{_tag('FACT: current bid' if c.get('bid') is not None else 'no bid yet')}</td></tr>"
            f"<tr><th>Estimated sellable units</th><td>{u.group(1) + ' stated in the title' if u else 'UNKNOWN'}{_tag('SELLER-STATED, unverified' if u else 'not estimated')}</td></tr>"
            + unk("Testing / sort burden") + unk("Expected recovery") + unk("Sell-through speed") + unk("Storage / handling") + unk("Downside")
            + "</table><p class='small mut'>The engine has no pallet model, so none of these are estimated here. Not ranked.</p></li>")


def render(s: dict) -> str:
    """The panel. Display only."""
    top = (f"<h2>DealSniffer Suggestions</h2><p class='small mut'>Ranked by the economics engine's capital velocity. Rules applied: about {_capl(s['cap'])} per purchase, "
           f"repair allowance up to ${s['repair_max']:,.0f}, your own resale target overrides the engine's. Display only: nothing here bids, contacts or spends.</p>")
    body = ("<ol class='sg-list'>" + "".join(render_ranked(r) for r in s["ranked"]) + "</ol>") if s["ranked"] else \
        "<p class='mut' id='sg-none'>No listing passes the engine and your rules right now. Nothing is ranked on a guess.</p>"
    if s["research"]:
        body += (f"<details class='mk-sec' id='sg-research'><summary><b>Needs research ({len(s['research'])}): too many unknowns to rank</b></summary><ul>"
                 + "".join(f"<li>{e(r['card']['title'])}: <span class='unk'>UNKNOWN: {e('; '.join(r['unknown']))}</span></li>" for r in s["research"][:25]) + "</ul></details>")
    if s["outside"]:
        body += (f"<details class='mk-sec' id='sg-outside'><summary><b>Scored but outside your rules ({len(s['outside'])})</b></summary><ul>"
                 + "".join(f"<li>{e(r['card']['title'])}: {e('; '.join(r['why_not']))}</li>" for r in s["outside"][:25]) + f"<li class='small mut'>Per-purchase cap: {_capl(s['cap'])}</li>" + "</ul></details>")
    if s["pallets"]:
        body += (f"<details class='mk-sec' id='sg-pallets'><summary><b>Pallet / wholesale ({len(s['pallets'])}): not ranked</b></summary><ul>"
                 + "".join(render_pallet(c) for c in s["pallets"][:10]) + "</ul></details>")
    if s["events"]:
        body += f"<p class='small mut' id='sg-events'>{s['events']} auction event(s) have no price and are not ranked as deals.</p>"
    return f"<section class='card' id='suggestions'>{top}{body}</section>"
