"""F-18: the Weekly Mission page, a READ-ONLY render of a mission plan (`mission.schema.json`, A-23).

* The plan document comes from a local file (`MBOS_MISSION_PLAN_FILE`, or `App(mission_file=...)`): there is no spine producer
  yet. It is validated with `mbos.mission.plan_errors` (schema + the ledger arithmetic, the spend cap and the gap rule). A plan
  that fails validation is NOT rendered as numbers: the page lists the errors instead.
* UNKNOWN stays UNKNOWN: a null target or hours is shown as UNKNOWN, and `remaining_gap` stays UNKNOWN then. The page never
  computes or fills in a number the plan does not carry (the only arithmetic is none).
* DO_NOT_SPEND is shown plainly, first. Every leg links to its card. Legs keep the plan's own order: ADR-0012, nothing here
  sorts or filters by absolute profit.
* Human channel only (R14): loopback, Host-checked, no forms, no writes.
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731

LEDGER_FIELDS = [("protected_principal", "Protected principal"), ("earned_working_capital", "Earned working capital"),
                 ("capital_deployed", "Capital deployed"), ("realized_profit", "Realized profit"),
                 ("available_to_deploy", "Available to deploy")]


def load_plan(path: Optional[str] = None) -> dict:
    """{'kind': 'plan'|'mission'|'none', 'doc', 'errors', 'path'}. Never raises; a bad file is reported."""
    p = path or os.environ.get("MBOS_MISSION_PLAN_FILE")
    if not p:
        return {"kind": "none", "doc": None, "errors": ["MBOS_MISSION_PLAN_FILE is not set: no mission plan available"], "path": None}
    try:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"kind": "none", "doc": None, "errors": ["mission plan file not found"], "path": p}
    except (OSError, ValueError) as ex:
        return {"kind": "none", "doc": None, "errors": [f"unreadable mission plan: {type(ex).__name__}"], "path": p}
    from mbos import mission

    if isinstance(doc, dict) and "legs" in doc:
        return {"kind": "plan", "doc": doc, "errors": mission.plan_errors(doc), "path": p}
    if isinstance(doc, dict) and "weekly_target_usd" in doc:
        errs = mission._check("mission", doc)
        return {"kind": "mission", "doc": doc, "errors": errs, "path": p}
    return {"kind": "none", "doc": None, "errors": ["unrecognised mission document"], "path": p}


def current_week(now: datetime) -> dict:
    """Monday..Sunday (UTC) containing `now`: only a calendar period for plan_from_db when no mission is set."""
    mon = (now - timedelta(days=now.weekday())).date()
    return {"start": mon.isoformat(), "end": (mon + timedelta(days=6)).isoformat()}


def load_live(backend: Any, now: datetime, path: Optional[str] = None) -> dict:
    """P-06-17: on lane D the plan is produced by 03's `mission_feed.plan_from_db` over live scorecards + the mission +
    `mbos.capital_position_document()` and validated with `plan_errors`; nothing is invented (no Items -> DO_NOT_SPEND/UNKNOWN).
    Anywhere else, or if the producer is unavailable or fails, fall back to the plan file (`load_plan`)."""
    reason = "not on lane D"
    if getattr(backend, "lane", None) == "lane_d":
        try:
            from mbos import mission
            from mbos_economics import mission_feed

            with backend.engine.connect() as c:
                cur = c.connection.cursor()
                doc = mission_feed.plan_from_db(cur, period=current_week(now))
            return {"kind": "plan", "doc": doc, "errors": mission.plan_errors(doc), "path": None, "source": "lane D (live Items)"}
        except Exception as ex:  # noqa: BLE001 - the page must still render; the fallback says why
            reason = f"live producer failed: {type(ex).__name__}"
    out = load_plan(path)
    out["source"] = f"file fallback ({reason})"
    return out


def money(v: Any) -> str:
    return "<b class='unk'>UNKNOWN</b>" if v is None else (f"${v:,.0f}" if isinstance(v, (int, float)) and not isinstance(v, bool) else e(v))


def _num(v: Any, unit: str = "") -> str:
    return "<b class='unk'>UNKNOWN</b>" if v is None else f"{e(v)}{e(unit)}"


def render_mission_header(m: dict) -> str:
    target, hours = m.get("weekly_target_usd"), m.get("hours_available")
    note = ""
    if target is None or hours is None:
        note = ("<p class='unk'><b>The weekly target and/or your hours are not set.</b> The system cannot judge the gap or the plan until "
                "you set them (MICHAEL_DECISIONS #10). It will not guess.</p>")
    return (f"<div class='card'><h2>Mission</h2><div class='row cap-row'>"
            f"<div class='cap-big'><div class='small mut'>Week</div><div class='cap-val'>{e(m['period']['start'])} to {e(m['period']['end'])}</div></div>"
            f"<div class='cap-big'><div class='small mut'>Weekly target</div><div class='cap-val'>{money(target)}</div></div>"
            f"<div class='cap-big'><div class='small mut'>Hours available</div><div class='cap-val'>{_num(hours, ' h')}</div></div></div>"
            f"{note}{'<p class=small>' + e(m.get('notes')) + '</p>' if m.get('notes') else ''}</div>")


def render_ledger(l: dict) -> str:
    rows = "".join(f"<tr><td>{label}</td><td class='num'>{money(l.get(k))}</td></tr>" for k, label in LEDGER_FIELDS)
    imp = (f"<tr><td class='bad'>Principal impairment</td><td class='num bad'>{money(l['principal_impairment'])}</td></tr>"
           if l.get("principal_impairment") else "")
    return (f"<div class='card'><h2>Capital position</h2><table>{rows}{imp}</table>"
            f"<p class='small mut'>As of {e(l.get('as_of'))}. Protected principal is the original bankroll; earned working capital is profit "
            "that has already come back.</p></div>")


def render_legs(legs: list[dict], known_items: set[str]) -> str:
    rows = []
    for l in legs:
        n = l["expected_net"]
        link = (f"<a href='/item/{e(l['item_id'])}'>open the card</a>" if l["item_id"] in known_items else
                f"<a href='/item/{e(l['item_id'])}'>card</a> <b class='bad'>(not in this store: unverified)</b>")
        rows.append(
            f"<tr><td>{e(l['opportunity_class'])}</td><td class='num'>{money(l['cash_at_risk'])}</td>"
            f"<td class='num'>{money(n['low'])} / <b>{money(n['likely'])}</b> / {money(n['high'])}</td>"
            f"<td class='num'>{_num(l['days_to_cash'], ' d')}</td><td class='num'>{_num(l['success_probability'])}</td>"
            f"<td class='num'>{_num(l['hours'], ' h')}</td><td>{e(l.get('why'))}</td><td>{link}</td></tr>")
    body = ("<div style='overflow-x:auto'><table><tr><th>Class</th><th>Cash at risk</th><th>Expected net (low / likely / high)</th>"
            "<th>Days to cash</th><th>Chance</th><th>Hours</th><th>Why</th><th>Card</th></tr>" + "".join(rows) + "</table></div>") if rows else "<p class='mut'>No legs.</p>"
    return f"<div class='card'><h2>Best next opportunities ({len(legs)})</h2>{body}<p class='small mut'>Plan order, not sorted by profit (ADR-0012).</p></div>"


def render_plan(doc: dict, known_items: set[str]) -> str:
    rec = doc["recommendation"]
    if rec == "DO_NOT_SPEND":
        banner = ("<div class='flash err' style='font-size:20px'><b>DO NOT SPEND.</b> The plan recommends committing no cash this week. "
                  "Service or other low-cash work is the better route to the target.</div>")
    elif rec == "DEPLOY":
        banner = "<div class='card'><h2>Recommendation</h2><p style='font-size:22px;margin:4px 0'><b>DEPLOY</b> capital to the legs below. Each still needs your own YES.</p></div>"
    else:
        banner = f"<div class='card'><h2>Recommendation</h2><p style='font-size:22px;margin:4px 0'><b>{e(rec)}</b></p></div>"
    pw = doc["projected_week"]
    gap = doc["remaining_gap"]
    gap_html = ("<b class='unk'>UNKNOWN</b> <span class='small mut'>(no target set, so there is no gap to compute)</span>" if gap is None
                else f"<b>{money(gap)}</b>")
    proj = (f"<div class='card'><h2>Projected week</h2><div class='row cap-row'>"
            f"<div class='cap-big'><div class='small mut'>Realized so far</div><div class='cap-val'>{money(doc['ledger'].get('realized_profit'))}</div></div>"
            f"<div class='cap-big'><div class='small mut'>Expected (low / likely / high)</div><div class='cap-val'>{money(pw['low'])} / {money(pw['likely'])} / {money(pw['high'])}</div></div>"
            f"<div class='cap-big'><div class='small mut'>Remaining gap</div><div class='cap-val'>{gap_html}</div></div>"
            f"<div class='cap-big'><div class='small mut'>Confidence</div><div class='cap-val'>{_num(doc['confidence'])}</div></div></div>"
            f"<p>{e(doc.get('explanation'))}</p></div>")
    stale = doc.get("replace_if_stale") or []
    unknowns = doc.get("unknowns") or []
    extra = ((f"<div class='card'><h2>Replace if stale</h2><ul>{''.join(f'<li><a href=/item/{e(i)}><code>{e(i)}</code></a></li>' for i in stale)}</ul></div>" if stale else "")
             + (f"<div class='card'><h2>UNKNOWN ({len(unknowns)})</h2><ul>{''.join(f'<li>{e(u)}</li>' for u in unknowns)}</ul></div>" if unknowns else ""))
    return (banner + render_mission_header(doc["mission"]) + proj + render_ledger(doc["ledger"]) + render_legs(doc["legs"], known_items) + extra)


def render_page(loaded: dict, known_items: set[str]) -> str:
    src = f" Source: {e(loaded['source'])}." if loaded.get("source") else ""
    head = ("<div class='card'><h2>Weekly mission</h2><p class='small mut'>Read-only. Built from live Items on lane D, else from a mission plan "
            f"file; nothing here spends, contacts or commits.{src}</p></div>")
    if loaded["kind"] == "none":
        return head + f"<div class='card'><p class='bad'>{e('; '.join(loaded['errors']))}</p></div>"
    if loaded["errors"]:
        return (head + "<div class='flash err'><b>This plan failed validation, so its numbers are not shown.</b><ul>"
                + "".join(f"<li>{e(x)}</li>" for x in loaded["errors"][:12]) + "</ul></div>")
    if loaded["kind"] == "mission":
        return head + render_mission_header(loaded["doc"]) + "<div class='card'><p class='unk'><b>No plan yet.</b> There is a mission but no plan built for it.</p></div>"
    return head + render_plan(loaded["doc"], known_items)
