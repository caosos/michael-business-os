"""Minimal local web UI (stdlib http.server; no JS, no framework).

Binds to 127.0.0.1 only and rejects non-local Host headers (DNS-rebinding guard).
Every POST carries a per-process CSRF token. Remote access and real step-up
(WebAuthn/TOTP) are lane E (Agent 05) work and are deliberately not attempted here.

R10: every decision goes through `backend.decide` → `mbos.spine.decide`. This module has no
gateway, no timers and no ledger of its own.
"""

import html
import json
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from mbos.clock import iso, utcnow
from mbos.spine import DecisionRefused

try:  # lane C's package is optional: without it the notes form is simply unavailable
    from mbos_economics.valueadd import NOTE_CATEGORIES, NOTE_KINDS
except ImportError:  # pragma: no cover
    NOTE_CATEGORIES, NOTE_KINDS = frozenset(), frozenset()

from . import card_view, ux, views
from .backend import ItemNotFound, NoteRefused, ProfileUnavailable
from .sources import load_health
from .ux import InputError

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#16181d;--mut:#5d6470;--line:#dde1e7;--acc:#2456c9;
--yes:#137a3c;--no:#b3261e;--mod:#8a5a00;--hold:#4b4f9e;--flip:#0e6e72;--svc:#7a3c9a;--warn:#fff4d6;--warnink:#6b4e00}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#111317;--card:#1a1d23;--ink:#e8eaee;--mut:#9aa2ae;
--line:#2c313a;--acc:#7aa2ff;--yes:#4cc17a;--no:#ff7a70;--mod:#e0a63a;--hold:#9ea2ff;--flip:#4fc7cc;--svc:#c792e6;--warn:#3a3014;--warnink:#f1d48a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
a{color:var(--acc)}header{padding:12px 16px;border-bottom:1px solid var(--line);display:flex;gap:12px;flex-wrap:wrap;align-items:center}
header b{font-size:17px}nav a{margin-right:12px}main{max-width:1060px;margin:0 auto;padding:16px}
.banner{background:var(--warn);color:var(--warnink);padding:8px 16px;font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:0 0 14px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:baseline}.grow{flex:1 1 auto}
.badge{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:700;letter-spacing:.03em;border:1px solid currentColor}
.flip{color:var(--flip)}.service{color:var(--svc)}.v-YES{color:var(--yes)}.v-PASS{color:var(--no)}.v-MAYBE{color:var(--mod)}
.mut{color:var(--mut)}.small{font-size:13px}h1{font-size:21px;margin:4px 0}h2{font-size:15px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:4px 6px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-weight:600;color:var(--mut);font-size:13px}td.num{text-align:right;font-variant-numeric:tabular-nums}
pre{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px;overflow:auto;font-size:13px;white-space:pre-wrap;word-break:break-word}
code{font-size:12.5px;word-break:break-all}
.decide{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.decide form{border:1px solid var(--line);border-radius:8px;padding:10px}
button{font:inherit;font-weight:700;border:0;border-radius:6px;padding:8px 14px;color:#fff;cursor:pointer;width:100%}
.b-YES{background:var(--yes)}.b-NO{background:var(--no)}.b-MODIFY{background:var(--mod)}.b-HOLD{background:var(--hold)}
input,textarea,select{font:inherit;width:100%;margin:4px 0 8px;padding:6px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink)}
input[type=checkbox],input[type=radio]{width:auto;margin-right:6px}textarea{min-height:120px;font-family:ui-monospace,monospace;font-size:13px}
.flash{padding:10px 14px;border-radius:8px;margin-bottom:14px;border:1px solid var(--line);background:var(--card)}.err{border-color:var(--no);color:var(--no)}
.unk{color:var(--mod)}.tag{display:inline-block;padding:0 6px;border-radius:99px;font-size:11px;font-weight:700;border:1px solid currentColor}
.tag.fact{color:var(--yes)}.tag.inf{color:var(--hold)}.tag.rec{color:var(--mod)}.rec{border-color:var(--acc)}
.q a.rowlink{display:block;text-decoration:none;color:inherit}.bad{color:var(--no);font-weight:600}.ok{color:var(--yes);font-weight:600}
"""

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731


def _money(v):
    return f"${v:,.0f}" if isinstance(v, (int, float)) else e(v)


def _fmt(row):
    v, u = row["value"], row["unit"]
    if u == "$":
        return _money(v)
    if u == "%":
        return f"{v * 100:.0f}%"
    return f"{e(v)}{'' if u in ('', None) else ' ' + u}"


def _lane(lane):
    return f'<span class="badge {e(lane)}">{"FLIP" if lane == "flip" else "SERVICE"}</span>'


def _verdict(v):
    return f'<span class="badge v-{e(v)}">System says {e(v)}</span>' if v else ""


def page(title, body, state, flash=None, error=False):
    f = f'<div class="flash{" err" if error else ""}">{e(flash)}</div>' if flash else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title><style>{CSS}</style></head>
<body><div class="banner">DRY-RUN · nothing leaves this machine · system {e(state)}</div>
<header><b>Operator UI</b><nav><a href="/">Queue</a><a href="/digest">Morning digest</a><a href="/summary">Daily summary</a><a href="/notes">My notes</a><a href="/holds">HOLD backlog</a><a href="/outcomes">Outcomes</a><a href="/sources">Source health</a><a href="/ledger">Receipt ledger</a></nav></header>
<main>{f}{body}</main></body></html>"""


def render_queue(q):
    def rows(lst, empty):
        if not lst:
            return f'<p class="mut">{empty}</p>'
        out = []
        for r in lst:
            extra = f' · held until {e(r["hold_until"])}' if r.get("hold_until") else ""
            extra += f' · modified from {e(r["derived_from"][:13])}…' if r.get("derived_from") else ""
            out.append(f"""<div class="card q"><a class="rowlink" href="/item/{e(r['item_id'])}">
<div class="row">{_lane(r['lane'])}<span class="mut small">{e(r['category'])}</span>{_verdict(r['verdict'])}
<span class="grow"></span><span class="small mut">{e(r['status'])} · expires in {e(r['expires_in_hours'])}h{extra}</span></div>
<h1>{e(r['title'])}</h1>
<div class="row small"><span>EV {_money(r['ev'])}</span><span>{_money(r['pph'])}/h</span>
<span>confidence {e(r['confidence'])}</span><span class="mut">{e(r['reversibility'])}</span></div>
<div>Proposed: <b>{e(r['summary'])}</b> <code>{e(r['capability'])}</code></div></a></div>""")
        return "".join(out)

    return (f"<h2>Needs your decision ({len(q['pending'])})</h2>{rows(q['pending'], 'Nothing waiting.')}"
            f"<h2>On hold ({len(q['held'])})</h2>{rows(q['held'], 'Nothing parked.')}"
            f"<h2>Closed / executed ({len(q['closed'])})</h2>{rows(q['closed'], 'None yet.')}")


def _ret(ret):
    return '<input type="hidden" name="return" value="item">' if ret else ""


def render_decide(c, csrf, ret=False):
    """YES / NO / MODIFY / HOLD forms for one open request. Human channel only (R14): CSRF + frozen payload hash.
    `ret` makes the POST come back to the opportunity card (/item/<id>) instead of the technical request page."""
    a = c["areq"]
    common = (f'<input type="hidden" name="csrf" value="{e(csrf)}">{_ret(ret)}'
              f'<input type="hidden" name="payload_hash_seen" value="{e(a["payload_hash"])}">')
    presets = "".join(
        f'<label><input type="radio" name="hold_preset" value="{e(k)}"{" checked" if k == "24h" else ""}>{e(v["label"])}</label><br>'
        for k, v in c["hold_presets"].items())
    decide = "<p class='mut'>This request is closed — no decision possible.</p>"
    if c["decidable"]:
        pin = ('<label>Step-up PIN (irreversible / money)<input name="pin" type="password" autocomplete="off" required></label>'
               if c["step_up"] else "")
        yes = (f"""<form method="post" action="/areq/{e(a['action_request_id'])}/decide">{common}<input type="hidden" name="decision" value="YES">
<p class="small">Executes <b>exactly</b> the frozen payload above (hash <code>{e(a['payload_hash'][7:19])}</code>). Dry-run only.</p>{pin}
<button class="b-YES">YES</button></form>""" if c["payload_hash_verified"] else
               "<div class='flash err'>YES unavailable: the payload shown does not hash to this request's payload_hash "
               "(ADR-0010 check). Use NO, MODIFY or HOLD, and report it.</div>")
        decide = f"""<div class="decide">
{yes}
<form method="post" action="/areq/{e(a['action_request_id'])}/decide">{common}<input type="hidden" name="decision" value="NO">
<label>Reason (required)<input name="reason" required maxlength="500"></label>
<p class="small mut">The opportunity is archived; the reason feeds LEARN.</p>
<button class="b-NO">NO</button></form>
<form method="post" action="/areq/{e(a['action_request_id'])}/decide">{common}<input type="hidden" name="decision" value="MODIFY">
<label>Edited payload (creates a NEW request that needs its own YES)<textarea name="new_payload">{e(json.dumps(a['payload'], indent=2))}</textarea></label>
<label>Note<input name="note" maxlength="500"></label><button class="b-MODIFY">MODIFY</button></form>
<form method="post" action="/areq/{e(a['action_request_id'])}/decide">{common}<input type="hidden" name="decision" value="HOLD">
{presets}<label>…or custom time (local)<input type="datetime-local" name="hold_until"></label>
<label>Reason<input name="reason" maxlength="500"></label><button class="b-HOLD">HOLD</button></form></div>"""
    return decide


def render_hold_notice(c, csrf, ret=False):
    a = c["areq"]
    hold = ""
    if c["hold"]:
        h = c["hold"]
        hold = (f"<p><b>On HOLD</b> until {e(h.get('hold_until'))} · wakes on {e(', '.join(h.get('wake_on') or []))}"
                f" · reminder every {e(h.get('renotify_after'))}"
                f"{' · escalates after ' + e(h['escalate_after']) if h.get('escalate_after') else ''}."
                " The item workflow owns this timer; it re-presents the request and never executes it.</p>")
        if "michael_ping" in (h.get("wake_on") or []):
            hold += (f'<form method="post" action="/areq/{e(a["action_request_id"])}/wake"><input type="hidden" name="csrf" value="{e(csrf)}">{_ret(ret)}'
                     '<button class="b-HOLD" style="width:auto">Wake now (re-present for a decision)</button></form>')
    return hold


def render_card(c, csrf):
    a, item = c["areq"], c["item"]
    loc = c["location"]
    econ = "".join(f"<tr><td>{e(r['label'])}</td><td class='num'>{_fmt(r)}</td></tr>" for r in c["economics"])
    rk = c["risk"]
    risk = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in [
        ("Risk sub-score", e(rk["risk_score"])), ("Max loss", _money(rk["max_loss"])),
        ("Reversibility", f'<span class="{"bad" if rk["reversibility"] == "irreversible" else ""}">{e(rk["reversibility"])}</span>'),
        ("Approval tier", f"{e(rk['tier'])} (Michael must decide)" if rk["tier"] == 0 else e(rk["tier"])),
        ("Untrusted inputs", '<span class="bad">yes — listing/inbound text was used</span>' if rk["untrusted_inputs_present"] else "no"),
        ("Source ToS risk", e(", ".join(rk["source_tos_risk"]) or "—")),
        ("Failed gates", f'<span class="bad">{e(", ".join(rk["failed_gates"]))}</span>' if rk["failed_gates"] else '<span class="ok">none</span>'),
        ("Flags", e(", ".join(rk["flags"]) or "—")),
    ])
    why = "".join(f"<li>{e(x)}</li>" for x in c["rationale"] + c["reasons"])
    cde = f"<p><b>Cheapest decisive evidence:</b> {e(c['cheapest_decisive_evidence'])}</p>" if c["cheapest_decisive_evidence"] else ""
    sources = "".join(
        f"<tr><td>{e(s['source'])}</td><td><a href='{e(s['url'])}' rel='noreferrer noopener'>{e(s['url'])}</a></td>"
        f"<td>{e(s['ingestion_method'])}</td><td>{e(s['first_seen_at'])}</td><td><code>{e((s.get('raw_ref') or '—')[:23])}</code></td></tr>"
        for s in c["sources"])
    research = "".join(f"<li><span class='badge'>{e(r['basis'])}</span> {e(r['finding'])} <code>{e(r['provenance_id'])}</code></li>" for r in c["research"])
    prov = "".join(
        f"<tr><td><code>{e(p['id'])}</code></td><td>{e(p['kind'])}</td><td>{e(p.get('basis'))}</td><td>{e(p.get('who'))}</td><td>{e(p['what'])}</td></tr>"
        for p in c["provenance"])
    receipts = "".join(
        f"<tr><td class='num'>{r['seq']}</td><td>{e(r['ts'])}</td><td>{e(r['type'])}</td><td>{e(r['actor']['id'])}</td>"
        f"<td>{e(r['intent'])}{' <b>[dry_run]</b>' if (r.get('effector_response') or {}).get('dry_run') else ''}"
        f"{' · msg ' + e(r['effector_response'].get('provider_msg_id')) if r.get('effector_response') else ''}</td>"
        f"<td><code>{e(r['row_hash'][7:19])}</code></td></tr>"
        for r in sorted(c["receipts"] + c["item_receipts"], key=lambda r: r["seq"]))
    apprs = "".join(
        f"<li><b>{e(x['decision'])}</b> by {e(x['decider'])} at {e(x['decided_at'])} via {e(x['channel'])}"
        f"{' · step-up' if (x.get('auth_context') or {}).get('step_up') else ''}"
        f"{' · reason: ' + e(x['reason']) if x.get('reason') else ''}"
        f"{' · hold ' + e(json.dumps(x['hold'])) if x.get('hold') else ''}"
        f"{' · new request <a href=/areq/' + e(x['modifications']['new_action_request_id']) + '>' + e(x['modifications']['new_action_request_id']) + '</a>' if x.get('modifications') else ''}</li>"
        for x in c["approvals"])
    lineage = ""
    if a.get("derived_from"):
        lineage += f"<p>Modified from <a href='/areq/{e(a['derived_from'])}'>{e(a['derived_from'])}</a></p>"
    for s in c["successors"]:
        lineage += f"<p>Superseded by <a href='/areq/{e(s)}'>{e(s)}</a></p>"
    hold = render_hold_notice(c, csrf)
    decide = render_decide(c, csrf)

    return f"""<div class="card"><div class="row">{_lane(c['lane'])}<span class="mut">{e(c['category'])} · {e(c['subcategory'])}</span>
{_verdict(c['verdict'])}<span class="grow"></span><span class="small mut">item {e(item['state'])} · request {e(a['status'])} · expires in {e(c['expires_in_hours'])}h</span></div>
<h1>{e(c['title'])}</h1><div class="mut small">{e(loc.get('city'))}, {e(loc.get('state'))} · {e(loc.get('road_miles_one_way'))} road miles one way</div>{hold}{lineage}</div>
<div class="grid">
<div class="card"><h2>Why the system recommends this</h2><p>Composite <b>{e(c['composite'])}</b> · confidence <b>{e(c['confidence'])}</b></p><ul>{why}</ul>{cde}</div>
<div class="card"><h2>Economics</h2><table>{econ}</table></div>
<div class="card"><h2>Confidence &amp; risk</h2><table>{risk}</table></div>
</div>
<div class="card"><h2>Proposed action</h2><p><b>{e(c['action_summary'] or a['capability'])}</b></p>
<div class="row small"><span><code>{e(a['capability'])}</code></span><span>category {e(a['category'])}</span><span>proposed by {e(a['proposed_by'])}</span>
<span>target {e((a.get('target') or {}).get('ref'))}</span></div>
<pre>{e(json.dumps(a['payload'], indent=2))}</pre>
<div class="small mut">payload_hash <code>{e(a['payload_hash'])}</code> · {"<span class='ok'>verified (MBOS-CJSON-1)</span>" if c["payload_hash_verified"] else "<span class='bad'>DOES NOT MATCH payload</span>"} · idempotency <code>{e(a['idempotency_key'])}</code></div></div>
<div class="card"><h2>Decide</h2>{decide}</div>
<div class="card"><h2>Sources</h2><table><tr><th>Source</th><th>URL</th><th>Method</th><th>First seen</th><th>raw_ref</th></tr>{sources}</table>
{'<h2 style="margin-top:12px">Research findings</h2><ul>' + research + '</ul>' if research else ''}</div>
<div class="card"><h2>Provenance (every fact, score and decision)</h2><table><tr><th>ID</th><th>Kind</th><th>Basis</th><th>Who</th><th>What</th></tr>{prov}</table></div>
{render_outcome_section(c, csrf)}
<div class="card"><h2>Decisions</h2>{'<ul>' + apprs + '</ul>' if apprs else '<p class="mut">None yet.</p>'}</div>
<div class="card"><h2>Receipts</h2><table><tr><th>seq</th><th>ts</th><th>type</th><th>actor</th><th>intent</th><th>row_hash</th></tr>{receipts}</table></div>"""


def render_ledger(store):
    v = store.verify_chain()
    status = (f"<span class='ok'>chain verified ({e(v['checked'])} receipts)</span>" if v["ok"]
              else f"<span class='bad'>CHAIN BROKEN at seq {e(v['first_bad_seq'])}: {e(v['reason'])}</span>")
    ok2, msg2 = store.verify_chain_independent()
    status += (f"<br><span class='{'ok' if ok2 else 'bad'}'>independent MBOS-RH-1 check (vendored reference): "
               f"{'' if ok2 else 'FAILED — '}{e(msg2)}</span>")
    rows = "".join(
        f"<tr><td class='num'>{r['seq']}</td><td>{e(r['ts'])}</td><td>{e(r['type'])}</td><td>{e(r['actor']['id'])}</td>"
        f"<td>{'<a href=/areq/' + e(r['action_request_id']) + '>' + e(r['action_request_id'][:13]) + '…</a>' if r.get('action_request_id') else ''}</td>"
        f"<td>{e(r['intent'])}</td><td><code>{e(', '.join(r['provenance_ids']))}</code></td><td><code>{e(r['row_hash'][7:19])}</code></td></tr>"
        for r in reversed(store.receipts(limit=300)))
    return (f"<div class='card'><h2>Receipt ledger</h2><p>{status}</p></div><div class='card'><table><tr><th>seq</th><th>ts</th><th>type</th><th>actor</th>"
            f"<th>request</th><th>intent</th><th>provenance</th><th>row_hash</th></tr>{rows}</table></div>")


def _num(v):
    """Plain text (callers HTML-escape it)."""
    return "—" if v is None else (f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, (int, float)) else str(v))


def _pva(o):
    return ", ".join(f"{p['field']}: {_num(p.get('predicted'))} → {_num(p.get('actual'))}" for p in o.get("predicted_vs_actual") or [])


def render_notes(notes, lane):
    if lane != "lane_d":
        return "<div class='card'><h2>My notes</h2><p class='bad'>Notes need the lane D store (<code>MBOS_STATE_BACKEND=lane_d</code>).</p></div>"
    rows = "".join(
        f"<tr><td>{e(n.get('entered_at'))}</td><td>{e(n.get('category'))}</td>"
        f"<td>{e(', '.join(g.get('makes', [])))} / {e(', '.join(g.get('models', [])))}</td><td>{e(n.get('kind'))}</td>"
        f"<td>{'<b class=bad>RETRACTED</b> ' if n.get('retracted') else ''}{e(n.get('statement'))}</td>"
        f"<td>{e(n.get('basis_of_knowledge'))}</td><td>{e(n.get('entered_by'))}</td>"
        f"<td><a href='/provenance/{e(n.get('provenance_id'))}'><code>{e(n.get('provenance_id'))}</code></a></td></tr>"
        for n in (g_ for g_ in notes) for g in [((n.get('match') or [{}])[0])])
    return ("<div class='card'><h2>My notes (your own model knowledge)</h2><p class='small mut'>Append-only and receipted. They show on cards as "
            "<b>RECOMMENDATION</b>, behind sourced recalls. Edits are new notes; retraction is not available from this page yet.</p>"
            "<table><tr><th>Entered</th><th>Category</th><th>Make / model</th><th>Kind</th><th>Statement</th><th>How I know</th>"
            f"<th>By</th><th>Provenance</th></tr>{rows or '<tr><td colspan=8 class=mut>No notes yet.</td></tr>'}</table></div>")


def render_outcome_card_section(app, item_id, open_areq, areqs):
    """Outcome entry/history under the opportunity card. Keyed by the item's latest request (outcomes belong to the item)."""
    latest = open_areq or (areqs[-1] if areqs else None)
    if latest is None:
        return ""
    return render_outcome_section(views.card(app.store, latest["action_request_id"], utcnow()), app.csrf, ret=True)


def render_outcome_section(c, csrf, ret=False):
    """F-09: outcomes already recorded for this item, and, once the item has settled, the entry form."""
    item, a = c["item"], c["areq"]
    rows = "".join(
        f"<tr><td>{e(o['observed_at'])}</td><td>{e(o['kind'])}</td>"
        f"<td>{e(', '.join(f'{k} {_num(v)}' for k, v in (o.get('realized') or {}).items()))}</td>"
        f"<td>{e(_pva(o))}</td>"
        f"<td>{e(o.get('notes'))}</td></tr>" for o in c.get("outcomes") or [])
    table = (f"<table><tr><th>Observed</th><th>Kind</th><th>Realized</th><th>Predicted → actual</th><th>Notes</th></tr>{rows}</table>"
             if rows else "<p class='mut'>No outcome recorded yet.</p>")
    form = ""
    if item["state"] in ux.OUTCOME_STATES:
        kinds = "".join(f"<option value='{e(k)}'>{e(k)}</option>" for k in ux.outcome_kinds(item["type"]))
        form = f"""<form method="post" action="/areq/{e(a['action_request_id'])}/outcome">
<input type="hidden" name="csrf" value="{e(csrf)}">{_ret(ret)}
<div class="decide"><label>What happened<select name="kind">{kinds}</select></label>
<label>Revenue $<input name="revenue" inputmode="decimal"></label><label>Total cost $<input name="total_cost" inputmode="decimal"></label>
<label>Hours spent<input name="hours" inputmode="decimal"></label><label>Days to cash<input name="days_to_cash" inputmode="decimal"></label></div>
<label>Notes<input name="notes" maxlength="1000"></label>
<button class="b-HOLD" style="width:auto">Record outcome (receipted; feeds LEARN)</button></form>"""
    else:
        form = f"<p class='small mut'>Outcome entry opens once the item has settled (now {e(item['state'])}).</p>"
    return f"<div class='card'><h2>Outcome</h2>{table}{form}</div>"


def render_holds(rows, now):
    if not rows:
        return "<div class='card'><h2>HOLD backlog</h2><p class='mut'>Nothing is parked.</p></div>"
    def until(r):
        return r["hold"].get("hold_until") or "9999"
    out = []
    overdue = 0
    for r in sorted(rows, key=until):
        a, item, h = r["action_request"], r["item"], r["hold"]
        late = bool(h.get("hold_until")) and h["hold_until"] < now.strftime("%Y-%m-%dT%H:%M:%S")
        overdue += late
        out.append(
            f"<tr><td>{_lane(item['type'])}</td><td><a href='/areq/{e(a['action_request_id'])}'>{e(item['normalized']['title'])}</a></td>"
            f"<td>{e(a['capability'])}</td><td>{e(r['held_at'])}</td>"
            f"<td class='{'bad' if late else ''}'>{e(h.get('hold_until'))}{' — OVERDUE (workflow should have re-presented)' if late else ''}</td>"
            f"<td>{e(', '.join(h.get('wake_on') or []))}</td><td>{e(r['reason'])}</td></tr>")
    note = f"<p class='bad'>{overdue} hold(s) past their wake time: check the worker is running.</p>" if overdue else ""
    return (f"<div class='card'><h2>HOLD backlog ({len(rows)})</h2>{note}<p class='small mut'>Read-only. Holds never execute; "
            "they re-present for a new decision. Open a card to decide or wake.</p><table><tr><th>Lane</th><th>Opportunity</th>"
            f"<th>Action</th><th>Held at</th><th>Wakes at</th><th>Wake on</th><th>Reason</th></tr>{''.join(out)}</table></div>")


def render_sources(h, now):
    head = f"<p class='small mut'>Read-only view of lane B's <code>health.json</code> ({e(h['path'] or 'not configured')}). "
    if h["updated_at"]:
        age_h = (now - h["updated_at"]).total_seconds() / 3600
        head += f"Last written {e(h['updated_at'].strftime('%Y-%m-%d %H:%M UTC'))}{' — <b class=bad>STALE (&gt;24h)</b>' if age_h > 24 else ''}. "
    head += "Clearing a freeze is a human CLI action on lane B (<code>--by</code> required), not done here.</p>"
    if h["error"]:
        return f"<div class='card'><h2>Source health</h2>{head}<p class='bad'>{e(h['error'])}</p></div>"
    rows = "".join(
        f"<tr><td>{e(r['source'])}</td><td class='{'bad' if r['status'] != 'HEALTHY' else 'ok'}'>{e(r['status'])}</td>"
        f"<td class='num'>{e(r['consecutive_failures'])}</td><td class='num'>{e(r['consecutive_blocks'])}</td>"
        f"<td class='num'>{e(r['total_failures'])}/{e(r['total_runs'])}</td><td>{e(r['last_success_at'])}</td>"
        f"<td class='num'>{e(r['last_items_seen'])}</td>"
        f"<td>{e((r['last_error'] or {}).get('kind') if isinstance(r['last_error'], dict) else r['last_error'])}"
        f"{' ' + e((r['last_error'] or {}).get('message')) if isinstance(r['last_error'], dict) and r['last_error'].get('message') else ''}</td>"
        f"<td>{e(r['freeze_reason'])}</td></tr>" for r in h["rows"])
    frozen = sum(1 for r in h["rows"] if r["status"] == "FROZEN")
    return (f"<div class='card'><h2>Source health ({len(h['rows'])} sources, {frozen} frozen)</h2>{head}"
            "<table><tr><th>Source</th><th>Status</th><th>Fails in a row</th><th>Blocks in a row</th><th>Failures/runs</th>"
            f"<th>Last success</th><th>Items last run</th><th>Last error</th><th>Freeze</th></tr>{rows}</table></div>")


def render_outcomes(rows, store):
    if not rows:
        return "<div class='card'><h2>Outcomes</h2><p class='mut'>None recorded yet.</p></div>"
    out = []
    for o in rows:
        item = store.item(o["item_id"]) or {"normalized": {"title": o["item_id"]}, "type": "?"}
        link = f"/areq/{e(o['action_request_id'])}" if o.get("action_request_id") else "#"
        out.append(f"<tr><td>{e(o['observed_at'])}</td><td><a href='{link}'>{e(item['normalized']['title'])}</a></td>"
                   f"<td>{e(o['kind'])}</td><td class='num'>{e(_num((o.get('realized') or {}).get('net_profit')))}</td>"
                   f"<td>{e(o.get('notes'))}</td></tr>")
    return (f"<div class='card'><h2>Outcomes ({len(rows)})</h2><table><tr><th>Observed</th><th>Opportunity</th><th>Kind</th>"
            f"<th>Net $</th><th>Notes</th></tr>{''.join(out)}</table></div>")


_BUCKET_LABEL = {"act_alert": "ACT NOW (alert)", "act": "Decide", "research": "Research", "research_r13": "Research before discarding (R13)"}


def render_digest(view):
    if view["error"]:
        return f"<div class='card'><h2>Morning digest</h2><p class='bad'>{e(view['error'])}</p></div>"
    d = view["digest"]
    def prov(pid):
        return f"<a href='/provenance/{e(pid)}'><code>{e(pid)}</code></a>" if pid else "—"
    rows = []
    for r in d["rows"]:
        card = view["cards"].get(r["item_id"])
        title = e(r["title"])  # listing text: untrusted
        title = f"<a href='/areq/{e(card)}'>{title}</a>" if card else title
        rf = r["refs"]
        rows.append(
            f"<tr><td class='num'>{e(r['rank'])}</td><td><b>{e(_BUCKET_LABEL.get(r['bucket'], r['bucket']))}</b></td>"
            f"<td>{_lane(r['lane'])} <span class='small mut'>{e(r['category'])}</span><br>{title}</td>"
            f"<td><b>{e(r['action'])}</b><br><span class='small mut'>{e(r['reason'])}</span></td>"
            f"<td>{e(r['window'])}{'<br><span class=small>' + e(r['deadline']) + '</span>' if r.get('deadline') else ''}</td>"
            f"<td class='num'>{e(_num(r['value_per_hour']))}</td>"
            f"<td class='small'>scr <code>{e(rf.get('scorecard_id'))}</code><br>inputs <code>{e((rf.get('inputs_hash') or '')[:19])}</code><br>"
            f"rec <code>{e(rf.get('recommendation_id'))}</code><br>prov {prov(rf.get('provenance_id'))}</td></tr>")
    excl = d["excluded"] + view["precheck_excluded"]
    ex = "".join(f"<li><code>{e(x['item_id'])}</code>: {e(x['reason'])}</li>" for x in excl)
    counts = " · ".join(f"{e(_BUCKET_LABEL[k])}: {e(v)}" for k, v in d["counts"].items())
    p = d["provenance"]
    return (f"<div class='card'><h2>Morning digest</h2><p class='small mut'>As of {e(d['as_of'])} · horizon {e(d['horizon_hours'])} h · "
            f"ranking by lane C (<code>{e(p['tool_name'])} {e(p['tool_version'])}</code>, basis {e(p['basis'])}) · "
            f"digest hash <code>{e(d['digest_hash'][:23])}</code></p><p>{counts}</p></div>"
            f"<div class='card'><table><tr><th>#</th><th>Bucket</th><th>Opportunity</th><th>Next step · why</th><th>Deadline</th>"
            f"<th>Value $/h</th><th>Refs</th></tr>{''.join(rows) or '<tr><td colspan=7 class=mut>Nothing open to rank.</td></tr>'}</table></div>"
            f"<div class='card'><h2>Not ranked ({len(excl)})</h2>{'<ul>' + ex + '</ul>' if ex else '<p class=mut>None.</p>'}</div>")


def render_provenance(p, pid):
    if p is None:
        return f"<div class='card'><h2>Provenance</h2><p class='bad'>{e(pid)} not found in mbos.provenance.</p></div>"
    s = views._prov_summary(p)
    return (f"<div class='card'><h2>Provenance <code>{e(pid)}</code></h2><p><b>{e(s['kind'])}</b> · basis {e(s['basis'])} · "
            f"{e(s['who'])}</p><p>{e(s['what'])}</p><pre>{e(json.dumps(p, indent=2, sort_keys=True))}</pre></div>")


class App:
    """Turns form posts into `spine.decide` calls through the backend. No side effects of its own."""

    def __init__(self, backend, operator_pin=None, health_file=None):
        self.store = backend
        self.operator_pin = operator_pin
        self.health_file = health_file  # lane B health.json (else MBOS_SOURCE_HEALTH_FILE)
        self.csrf = secrets.token_urlsafe(32)
        self.session_id = "web-" + secrets.token_hex(4)

    def state(self):
        return self.store.system_state()

    def _check_csrf(self, f):
        if not secrets.compare_digest(f.get("csrf", ""), self.csrf):
            raise InputError("invalid form token; reload the page")

    def decide(self, areq_id, f):
        self._check_csrf(f)
        d, seen = f.get("decision"), f.get("payload_hash_seen") or ""
        areq = self.store.action_request(areq_id)
        if areq is None:
            raise InputError(f"unknown action request {areq_id}")
        if d not in ("YES", "NO", "MODIFY", "HOLD"):
            raise InputError(f"unknown decision {d!r}")
        kw = {"auth_context": ux.auth_context(areq, f.get("pin"), self.operator_pin, self.session_id, d)}
        reason = (f.get("reason") or f.get("note") or "").strip() or None
        if reason:
            kw["reason"] = reason
        if d == "NO" and not reason:
            raise InputError("NO requires a reason (it feeds LEARN)")
        if d == "MODIFY":
            try:
                kw["new_payload"] = json.loads(f.get("new_payload") or "")
            except json.JSONDecodeError as ex:
                raise InputError(f"edited payload is not valid JSON: {ex}")
            if not isinstance(kw["new_payload"], dict):
                raise InputError("edited payload must be a JSON object")
        if d == "HOLD":
            kw["hold"] = ux.hold_for(f.get("hold_preset") or "24h", utcnow(), f.get("hold_until") or None)
        out = self.store.decide(areq_id, d, seen, **kw)
        return {
            "YES": "YES recorded. The item workflow now runs it through the gateway (dry-run); watch the receipts below.",
            "NO": "NO recorded; the opportunity is archived.",
            "MODIFY": f"MODIFY recorded. New request {out.get('new_action_request_id')} awaits its own YES.",
            "HOLD": "HOLD recorded. The workflow re-notifies and re-presents it; it never executes on its own.",
        }[d], out

    def outcome(self, areq_id, f):
        """F-09: record an outcome for the card's item via spine.record_outcome (receipted). Human channel only."""
        self._check_csrf(f)
        areq = self.store.action_request(areq_id)
        if areq is None:
            raise InputError(f"unknown action request {areq_id}")
        item = self.store.item(areq["item_id"])
        if item["state"] not in ux.OUTCOME_STATES:
            raise InputError(f"the item is {item['state']}; record outcomes once it has settled")
        kind, kw = ux.parse_outcome(item, f)
        o = self.store.record_outcome(item["item_id"], kind, **kw)
        return f"Outcome {o['kind']} recorded ({o['outcome_id']})."

    author = "michael"  # the authenticated operator: set HERE, never taken from a form (F-14; all humans share one DB login)

    def add_note(self, item_id, f):
        """F-14: Michael's own model knowledge → spine_d.record_operator_note. Human channel only (R14): CSRF + PIN,
        and this is the only code path in the UI that calls it. Returns a flash message; raises with every reason."""
        self._check_csrf(f)
        if not self.operator_pin:
            raise InputError("step-up not configured (MBOS_OPERATOR_PIN unset); notes are refused (fail-closed)")
        if not f.get("pin") or not secrets.compare_digest(str(f["pin"]), str(self.operator_pin)):
            raise InputError("a PIN is required to enter a note (it identifies you as the author)")
        try:
            self.store.opportunity_card(item_id)
        except ItemNotFound:
            raise InputError("unknown opportunity") from None
        if not NOTE_CATEGORIES:
            raise InputError("lane C's package (mbos_economics) is not installed; notes are unavailable")
        bundle = ux.parse_note(f, self.author, iso(utcnow()))
        note_id = self.store.record_operator_note(bundle)
        return f"Note saved ({note_id}). It will show on this model's cards as your recommendation."

    def wake(self, areq_id, f):
        self._check_csrf(f)
        areq = self.store.action_request(areq_id)
        if areq is None or areq["status"] != "held":
            raise InputError("only a held request can be woken")
        self.store.ping(areq["item_id"])
        return "Wake sent. The workflow re-presents the request (it does not execute it)."


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        server_version = "OperatorUI"
        sys_version = ""

        def log_message(self, fmt, *args):  # quiet; the receipt ledger is the audit log
            pass

        def _send(self, status, body, ctype="text/html; charset=utf-8", headers=None):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0] if not (self.headers.get("Host") or "").startswith("[") \
                else (self.headers.get("Host") or "").split("]")[0] + "]"
            if host not in ALLOWED_HOSTS:
                self._send(HTTPStatus.FORBIDDEN, "forbidden host", "text/plain")
                return False
            return True

        def do_GET(self):
            if not self._host_ok():
                return
            u = urlparse(self.path)
            qs = parse_qs(u.query)
            now = utcnow()
            flash = (qs.get("msg") or [None])[0]
            err = (qs.get("err") or [None])[0]
            if u.path == "/":
                return self._send(200, page("Operator queue", render_queue(views.queue(app.store, now)), app.state(), flash or err, bool(err)))
            if u.path == "/digest":
                from . import digest as digest_view

                return self._send(200, page("Morning digest", render_digest(digest_view.build(app.store, iso(now))), app.state()))
            if u.path == "/notes":
                return self._send(200, page("My notes", render_notes(app.store.operator_notes(), app.store.lane), app.state(), flash or err, bool(err)))
            if u.path.startswith("/item/"):
                return self._item_page(u.path.split("/")[2], now, flash or err, bool(err))
            if u.path == "/summary":
                from . import summary as summary_view

                s_ = summary_view.build_summary(app.store, now, health_file=app.health_file)
                return self._send(200, page("Daily summary", "<div class='card'>" + summary_view.render_html_body(s_) +
                                            "<p class='small mut'>Files on disk: <code>python -m operator_ui summary --out-dir DIR</code>"
                                            " (local only; never sent).</p></div>", app.state()))
            if u.path.startswith("/provenance/"):
                pid = u.path.split("/")[2]
                return self._send(200, page("Provenance", render_provenance(app.store.provenance(pid), pid), app.state()))
            if u.path == "/holds":
                return self._send(200, page("HOLD backlog", render_holds(app.store.held(), now), app.state()))
            if u.path == "/sources":
                return self._send(200, page("Source health", render_sources(load_health(app.health_file), now), app.state()))
            if u.path == "/outcomes":
                return self._send(200, page("Outcomes", render_outcomes(app.store.outcomes(), app.store), app.state()))
            if u.path == "/ledger":
                return self._send(200, page("Receipt ledger", render_ledger(app.store), app.state()))
            if u.path.startswith("/areq/"):
                c = views.card(app.store, u.path.split("/")[2], now)
                if c is None:
                    return self._send(404, page("Not found", "<p>No such request.</p>", app.state()))
                return self._send(200, page(c["title"], render_card(c, app.csrf), app.state(), flash or err, bool(err)))
            if u.path == "/api/queue.json":
                return self._send(200, json.dumps(views.queue(app.store, now)), "application/json")
            if u.path.startswith("/api/areq/"):
                c = views.card(app.store, u.path.split("/")[3].removesuffix(".json"), now)
                if c is None:
                    return self._send(404, "{}", "application/json")
                return self._send(200, json.dumps({k: v for k, v in c.items() if k != "hold_presets"}, default=str), "application/json")
            return self._send(404, page("Not found", "<p>Not found.</p>", app.state()))

        def _post_note(self, item_id):
            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True).items()}
            try:
                msg = app.add_note(item_id, f)
            except (ux.NoteInputError, NoteRefused) as ex:  # re-render the card with every reason and the typed values
                return self._item_page(item_id, utcnow(), None, False, note_reasons=ex.reasons,
                                       note_values={k: v for k, v in f.items() if k not in ("pin", "csrf")})
            except InputError as ex:
                return self._item_page(item_id, utcnow(), None, False, note_reasons=[str(ex)],
                                       note_values={k: v for k, v in f.items() if k not in ("pin", "csrf")})
            self.send_response(303)
            self.send_header("Location", f"/item/{item_id}?msg={quote(msg)}#note")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _item_page(self, item_id, now, flash, is_err, note_reasons=None, note_values=None):
            """F-13: the opportunity card is the primary view of an item."""
            try:
                res = app.store.opportunity_card(item_id)
            except ItemNotFound:
                return self._send(404, page("Not found", "<p>No such opportunity.</p>", app.state()))
            except ProfileUnavailable as ex:
                return self._send(503, page("Card unavailable", f"<div class='card'><h2>Card unavailable</h2><p class='bad'>{e(ex)}</p>"
                                            "<p>The technical request pages still work.</p></div>", app.state()))
            card = res["card"]
            open_areq = next((a for a in reversed(res["areqs"]) if a["status"] in ("pending_approval", "held")), None)
            controls = hold = ""
            if open_areq:
                v = views.card(app.store, open_areq["action_request_id"], now)
                controls, hold = render_decide(v, app.csrf, ret=True), render_hold_notice(v, app.csrf, ret=True)
                controls += f"<p class='small'><a href='/areq/{e(open_areq['action_request_id'])}'>Technical view of this request (payload, hashes)</a></p>"
            body = card_view.render_item_card(card, res["errors"], controls, hold)
            body += card_view.render_note_section(card, app.csrf, app.store.lane == "lane_d", sorted(NOTE_CATEGORIES), sorted(NOTE_KINDS),
                                                  ux.NOTE_BASIS_CHOICES, flash_reasons=note_reasons, values=note_values)
            body += render_outcome_card_section(app, item_id, open_areq, res["areqs"])
            return self._send(200, page(card["item"]["title"], body, app.state(), flash, is_err))

        def do_POST(self):
            if not self._host_ok():
                return
            u = urlparse(self.path)
            parts = u.path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "item" and parts[2] == "note":
                return self._post_note(parts[1])
            if len(parts) != 3 or parts[0] != "areq" or parts[2] not in ("decide", "wake", "outcome"):
                return self._send(404, "not found", "text/plain")
            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True).items()}
            areq_id = parts[1]
            try:
                if parts[2] == "wake":
                    msg, target = app.wake(areq_id, f), areq_id
                elif parts[2] == "outcome":
                    msg, target = app.outcome(areq_id, f), areq_id
                else:
                    msg, out = app.decide(areq_id, f)
                    target = out.get("new_action_request_id") or areq_id
                loc, key = f"/areq/{target}", "msg"
                if f.get("return") == "item":
                    loc = f"/item/{app.store.action_request(target)['item_id']}"
            except (InputError, DecisionRefused) as ex:
                loc, key, msg = f"/areq/{areq_id}", "err", str(ex)
                if f.get("return") == "item" and app.store.action_request(areq_id):
                    loc = f"/item/{app.store.action_request(areq_id)['item_id']}"
            self.send_response(303)
            self.send_header("Location", f"{loc}?{key}={quote(msg)}")
            self.send_header("Content-Length", "0")
            self.end_headers()

    return H


def serve(app, host="127.0.0.1", port=8765):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("refusing to bind a non-loopback address: remote access needs lane E auth (WebAuthn/TOTP)")
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"Operator UI on http://{host}:{port}/  (dry-run; decisions go to spine.decide; Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
