"""Minimal local web UI (stdlib http.server; no JS, no framework).

Binds to 127.0.0.1 only and rejects non-local Host headers (DNS-rebinding guard).
Every POST carries a per-process CSRF token. Remote access and real step-up
(WebAuthn/TOTP) are lane E (Agent 05) work and are deliberately not attempted here.

R10: every decision goes through `backend.decide` → `mbos.spine.decide`. This module has no
gateway, no timers and no ledger of its own.
"""

import html
import json
import os
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from mbos.clock import iso, utcnow
from mbos.spine import DecisionRefused

try:  # lane C's package is optional: without it the notes form is simply unavailable
    from mbos_economics.valueadd import NOTE_CATEGORIES, NOTE_KINDS
except ImportError:  # pragma: no cover
    NOTE_CATEGORIES, NOTE_KINDS = frozenset(), frozenset()

from . import deal_ui, landing_fix, live_demo, market_routes, resale_view, attest_view, bought_view, card_view, comps_view, glance_view, inputs_view, ux, views, wanted_view
from .digest import figures as digest_figures, dollars as _dollars
from .card_view import ec
from .backend import AlreadyClosed, FollowupRefused, ItemNotFound, NoteRefused, NumbersRefused, ProfileUnavailable
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
.cap-row{gap:18px;align-items:flex-start}.cap-big{min-width:150px}.cap-val{font-size:22px;font-weight:700}
.unk{color:var(--mod)}.tag{display:inline-block;padding:0 6px;border-radius:99px;font-size:11px;font-weight:700;border:1px solid currentColor}
.tag.fact{color:var(--yes)}.tag.inf{color:var(--hold)}.tag.rec{color:var(--mod)}.rec{border-color:var(--acc)}
nav a.active{font-weight:700;text-decoration:none;color:var(--ink);border-bottom:2px solid var(--acc)}h1.pagehead{font-size:22px;margin:0 0 12px}
.lbl{display:inline-block;padding:0 6px;border-radius:4px;font-size:11px;font-weight:700;background:var(--warn);color:var(--warnink)}
.ph{position:relative;width:132px;height:99px;flex:none;border:1px solid var(--line);border-radius:8px;background:var(--bg);overflow:hidden;display:flex;align-items:center;justify-content:center;text-align:center;font-size:12px;color:var(--mut);padding:4px}
.ph img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;background:var(--bg)}.ph.big{width:min(100%,480px);height:auto;aspect-ratio:4/3}
.gallery{display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap}.gtxt{flex:1 1 180px}.enl figure,.mock figure{margin:8px 0}
.dealtop{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap}.dt{text-transform:none;letter-spacing:0;font-size:17px;color:var(--ink)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:10px 0}.kpi{border:1px solid var(--line);border-radius:8px;padding:6px 8px}.kpi b{display:block;font-size:15px}
.next{background:var(--bg);border-left:4px solid var(--acc);padding:6px 10px;border-radius:4px}.ad{white-space:pre-wrap;word-break:break-word;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px;font-size:14px}
.fgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:6px 12px}.chip{display:inline-block;margin:0 6px 4px 0;padding:2px 10px;border:1px solid var(--line);border-radius:99px;text-decoration:none}.chip.on{border-color:var(--acc);font-weight:700}
.proof pre{max-height:320px}details>summary{cursor:pointer}
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


NAV = [("/market", "Marketplace", None), ("/queue", "Queue", None), ("/mission", "Weekly mission", None), ("/numbers", "My numbers", None), ("/wanted", "Wanted", None),
       ("/usage", "Usage", "usage"), ("/intake", "Intake", None), ("/assets", "My assets", None), ("/resale", "Resale", None), ("/owner-listing", "Add a listing", None), ("/gsa", "GSA lots", None), ("/preview", "Audience previews", "preview"),
       ("/digest", "Morning digest", None), ("/summary", "Daily summary", None), ("/notes", "My notes", None),
       ("/holds", "HOLD backlog", None), ("/outcomes", "Outcomes", None), ("/sources", "Source health", "sources"),
       ("/ledger", "Receipt ledger", None)]
FROZEN_HELP = ("FROZEN means the global kill switch is on: nothing will be carried out, and a YES you give now ends as cancelled. "
               "Reading and entering numbers still work. To release it, run on the server as the owner: "
               "<code>mbos panic off --reason \"why it is safe\"</code> (it is receipted).")


class UiState(str):
    """The system state text plus what the page chrome needs (F-88, F-100): which tabs have no data source configured, and whether
    owner-channel writes would run on the worker login. A plain str everywhere else."""

    hidden: frozenset = frozenset()
    owner_login_missing: bool = False


_CUR = threading.local()  # the path of the request being served, so the page chrome can mark the active tab (F-45)
NAV_ALIAS = {"/areq": "/queue", "/item": "/queue", "/": "/market", "/provenance": "/ledger"}


def _active(path):
    path = path or ""
    first = "/" + path.strip("/").split("/")[0] if path.strip("/") else "/"
    first = NAV_ALIAS.get(first, first)
    return first


def _nav(state):
    hidden = getattr(state, "hidden", frozenset())
    cur = _active(getattr(_CUR, "path", ""))
    return "".join(f'<a href="{h}"{" class=active aria-current=page" if h == cur else ""}>{t}</a>' for h, t, k in NAV if k not in hidden)


def _notices(state):
    out = ""
    if str(state).startswith("FROZEN"):
        out += f'<div class="flash err" id="frozen"><b>System FROZEN.</b> {FROZEN_HELP}</div>'
    if getattr(state, "owner_login_missing", False):
        out += ('<div class="flash err" id="owner-login"><b>Owner writes will be refused.</b> This UI is running on the worker login, not '
                'the owner login, so saving My numbers, a Wanted campaign or a confirmation will fail with "permission denied". '
                'Set <code>MBOS_OWNER_DATABASE_URL</code> (<code>source var/owner.env</code>) and restart the UI.</div>')
    return out


def page(title, body, state, flash=None, error=False):
    f = f'<div class="flash{" err" if error else ""}">{e(flash)}</div>' if flash else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{ec(title)}</title><style>{CSS}</style></head>
<body><div class="banner">DRY-RUN · nothing leaves this machine · system {e(state)}</div>
<header><b>Operator UI</b><nav>{_nav(state)}</nav></header>{_notices(state)}
<main>{f}{'' if '<h1' in body else f'<h1 class="pagehead">{ec(title)}</h1>'}{body}</main></body></html>"""


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
<h1>{ec(r['title'])}</h1>
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
<h1>{ec(c['title'])}</h1><div class="mut small">{e(loc.get('city'))}, {e(loc.get('state'))} · {e(loc.get('road_miles_one_way'))} road miles one way</div>{hold}{lineage}</div>
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


def render_notes(notes, lane, csrf="", reasons=None, flash_note=None):
    """/notes: Michael's own model knowledge. Edit = a new version (supersedes); Retract = a new retraction row. Both need the
    PIN, use the server-set author, and show every refusal reason. History is never edited."""
    if lane != "lane_d":
        return "<div class='card'><h2>My notes</h2><p class='bad'>Notes need the lane D store (<code>MBOS_STATE_BACKEND=lane_d</code>).</p></div>"
    errs = ("<div class='flash err'><b>Not saved.</b><ul>" + "".join(f"<li>{e(r)}</li>" for r in (reasons or [])) + "</ul></div>") if reasons else ""
    opts = lambda xs, sel: "".join(f"<option value='{e(x)}'{' selected' if x == sel else ''}>{e(x)}</option>" for x in xs)  # noqa: E731
    cats, kinds = sorted(NOTE_CATEGORIES), sorted(NOTE_KINDS)

    def actions(n):
        if n.get("retracted"):
            return "<span class='small mut'>retracted (history kept)</span>"
        g = (n.get("match") or [{}])[0]
        choice, detail = ux.split_basis(n.get("basis_of_knowledge") or "")
        nid = e(n["note_id"])
        pin = '<label>PIN<input name="pin" type="password" autocomplete="off" required></label>'
        return (f"<details><summary>Edit</summary><form method='post' action='/notes/{nid}/edit'><input type='hidden' name='csrf' value='{e(csrf)}'>"
                f"<label>Category<select name='category'>{opts(cats, n.get('category'))}</select></label>"
                f"<label>Make(s)<input name='makes' value='{e(', '.join(g.get('makes', [])))}' required></label>"
                f"<label>Model(s)<input name='models' value='{e(', '.join(g.get('models', [])))}' required></label>"
                f"<label>Kind<select name='kind'>{opts(kinds, n.get('kind'))}</select></label>"
                f"<label>Statement<textarea name='statement' maxlength='600' required>{e(n.get('statement'))}</textarea></label>"
                f"<label>Plan hint<input name='plan_hint' value='{e(n.get('plan_hint'))}' maxlength='600'></label>"
                f"<label>How do you know?<select name='basis_of_knowledge'>{opts(ux.NOTE_BASIS_CHOICES, choice)}</select></label>"
                f"<label>Detail<input name='basis_detail' value='{e(detail)}' maxlength='200'></label>"
                f"<label>Reference (https)<input name='reference_url' value='{e(n.get('reference_url'))}'></label>{pin}"
                "<button class='b-HOLD' style='width:auto'>Save as a new version</button></form></details>"
                f"<details><summary>Retract</summary><form method='post' action='/notes/{nid}/retract'><input type='hidden' name='csrf' value='{e(csrf)}'>"
                f"<label>Reason (required)<input name='reason' maxlength='300' required></label>{pin}"
                "<button class='b-NO' style='width:auto'>Retract this note</button></form></details>")

    pin = '<label>PIN<input name="pin" type="password" autocomplete="off" required></label>'
    add = (f"<details id='add-note' open><summary><b>Add note</b></summary><form method='post' action='/notes/add'><input type='hidden' name='csrf' value='{e(csrf)}'>"
           f"<label>Category<select name='category'>{opts(cats, None)}</select></label><label>Make(s)<input name='makes' required></label>"
           f"<label>Model(s)<input name='models' required></label><label>Kind<select name='kind'>{opts(kinds, None)}</select></label>"
           "<label>Statement<textarea name='statement' maxlength='600' required></textarea></label><label>Plan hint<input name='plan_hint' maxlength='600'></label>"
           f"<label>How do you know?<select name='basis_of_knowledge'>{opts(ux.NOTE_BASIS_CHOICES, None)}</select></label>"
           f"<label>Detail<input name='basis_detail' maxlength='200'></label><label>Reference (https)<input name='reference_url'></label>{pin}"
           "<button class='b-HOLD' style='width:auto'>Add note</button></form></details>")
    rows = "".join(
        f"<tr><td>{e(n.get('entered_at'))}</td><td>{e(n.get('category'))}</td>"
        f"<td>{e(', '.join(g.get('makes', [])))} / {e(', '.join(g.get('models', [])))}</td><td>{e(n.get('kind'))}</td>"
        f"<td>{'<b class=bad>RETRACTED</b> ' if n.get('retracted') else ''}{ec(n.get('statement'), 700)}</td>"
        f"<td>{ec(n.get('basis_of_knowledge'), 300)}</td><td>{e(n.get('entered_by'))}</td>"
        f"<td><a href='/provenance/{e(n.get('provenance_id'))}'><code>{e(n.get('provenance_id'))}</code></a>"
        f"{'<br><span class=small>revisions: ' + e(n.get('revisions')) + '</span>' if n.get('revisions') else ''}</td>"
        f"<td>{actions(n)}</td></tr>"
        for n in notes for g in [((n.get('match') or [{}])[0])])
    return (f"<div class='card'><h2>My notes (your own model knowledge)</h2>{errs}<p class='small mut'>Append-only and receipted. They show on cards as "
            "<b>RECOMMENDATION</b>, behind sourced recalls. An edit saves a <b>new version</b>; a retraction is a new row. Nothing is overwritten.</p>"
            f"{add}<div style='overflow-x:auto'><table><tr><th>Entered</th><th>Category</th><th>Make / model</th><th>Kind</th><th>Statement</th><th>How I know</th>"
            f"<th>By</th><th>Provenance</th><th>Change</th></tr>{rows or '<tr><td colspan=9 class=mut>No notes yet.</td></tr>'}</table></div></div>")


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
<p class="small mut">No PIN is needed here: recording what happened is receipted and cannot approve, spend or contact anyone. A sale does move your ledger (principal back, profit earned), and a second close of the same item is refused.</p>
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
            f"<tr><td>{_lane(item['type'])}</td><td><a href='/areq/{e(a['action_request_id'])}'>{ec(item['normalized']['title'])}</a></td>"
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
        out.append(f"<tr><td>{e(o['observed_at'])}</td><td><a href='{link}'>{ec(item['normalized']['title'])}</a></td>"
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
        title = ec(r["title"])  # listing text: untrusted (clean_text + escape)
        title = f"<a href='/areq/{e(card)}'>{title}</a>" if card else title
        rf = r["refs"]
        dg = digest_figures(r)
        rows.append(
            f"<tr><td class='num'>{e(r['rank'])}</td><td><b>{e(_BUCKET_LABEL.get(r['bucket'], r['bucket']))}</b></td>"
            f"<td>{_lane(r['lane'])} <span class='small mut'>{e(r['category'])}</span><br>{title}</td>"
            f"<td><b>{e(r['action'])}</b><br><span class='small mut'>{e(r['reason'])}</span></td>"
            f"<td>{e(r['window'])}{'<br><span class=small>' + e(r['deadline']) + '</span>' if r.get('deadline') else ''}</td>"
            f"<td class='num'>{e(_dollars(dg['priority'], ''))}</td><td class='num'>{e(_dollars(dg['ev']))}<br><span class='small mut'>{e(_dollars(dg['ev_per_hour']))}/h</span></td>"
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
            f"<th title='Lane C rank score: orders this list; it is not dollars'>Priority score</th><th>Expected profit, weighted by chance<br><span class='small mut'>and per hour</span></th><th>Refs</th></tr>{''.join(rows) or '<tr><td colspan=8 class=mut>Nothing open to rank.</td></tr>'}</table></div>"
            f"<div class='card'><h2>Not ranked ({len(excl)})</h2>{'<ul>' + ex + '</ul>' if ex else '<p class=mut>None.</p>'}</div>")


def render_provenance(p, pid):
    if p is None:
        return f"<div class='card'><h2>Provenance</h2><p class='bad'>{e(pid)} not found in mbos.provenance.</p></div>"
    s = views._prov_summary(p)
    return (f"<div class='card'><h2>Provenance <code>{e(pid)}</code></h2><p><b>{e(s['kind'])}</b> · basis {e(s['basis'])} · "
            f"{e(s['who'])}</p><p>{e(s['what'])}</p><pre>{e(json.dumps(p, indent=2, sort_keys=True))}</pre></div>")


class App:
    """Turns form posts into `spine.decide` calls through the backend. No side effects of its own."""

    def __init__(self, backend, operator_pin=None, health_file=None, mission_file=None, inventory_file=None,
                 telemetry_dir=None, queue_file=None, campaigns_file=None, policy_path=None, comps_inbox=None):
        self.store = backend
        self.campaigns = wanted_view.CampaignStore(campaigns_file or os.environ.get("MBOS_CAMPAIGNS_FILE"))  # F-23
        self.policy_path = policy_path
        self.comps_inbox = comps_inbox or os.environ.get("MBOS_COMPS_INBOX")  # F-28: the ManualCompsAdapter inbox (A-39)
        self.operator_pin = operator_pin
        self.inventory_file = inventory_file  # inventory JSON to preview (MBOS_INVENTORY_FILE)
        self.telemetry_dir = telemetry_dir  # MBOS_TELEMETRY_DIR (read-only)
        self.queue_file = queue_file  # READY_QUEUE.md copy (MBOS_READY_QUEUE_FILE)
        self.mission_file = mission_file  # mission plan JSON (MBOS_MISSION_PLAN_FILE)
        self.health_file = health_file  # lane B health.json (else MBOS_SOURCE_HEALTH_FILE)
        self.resale = resale_view.Book()  # F-39: in-memory DRY-RUN resale ledger
        self.tow: dict = {}  # F-45: the owner's own tow vehicle and limits (editable; nothing is hard-coded)
        self.presets: dict = {}  # F-45: saved filter presets, in memory
        self.deals = dict(resale_view.DEMO_DEALS)  # F-39: labelled DEMO lots until a feed provides them
        self.assets = {}  # F-34: in-memory DRY-RUN owned-asset drafts
        self.owner_listings: dict = {}  # F-46: OWNER-SUPPLIED url/photos/text, in memory, DRY-RUN
        self.intake_drafts = {}  # F-20: in-memory DRY-RUN drafts, never published
        self.csrf = secrets.token_urlsafe(32)
        self.session_id = "web-" + secrets.token_hex(4)
        self.pin_gate = ux.PinGate()  # F-77: shared by every PIN check in this process

    def state(self):
        st = UiState(self.store.system_state())
        hidden = set()
        if not (self.health_file or os.environ.get("MBOS_SOURCE_HEALTH_FILE")):
            hidden.add("sources")
        if not (self.telemetry_dir or os.environ.get("MBOS_TELEMETRY_DIR") or self.queue_file or os.environ.get("MBOS_READY_QUEUE_FILE")):
            hidden.add("usage")
        if not (self.inventory_file or os.environ.get("MBOS_INVENTORY_FILE")):
            hidden.add("preview")
        st.hidden = frozenset(hidden)  # F-100: a tab whose data source is not configured is not offered
        st.owner_login_missing = getattr(self.store, "owner_login", None) is False and getattr(self.store, "lane", "") == "lane_d"
        return st

    def _check_csrf(self, f):
        if not ux.same(f.get("csrf", ""), self.csrf):
            raise InputError("invalid form token; reload the page")

    def decide(self, areq_id, f):
        self._check_csrf(f)
        d, seen = f.get("decision"), f.get("payload_hash_seen") or ""
        areq = self.store.action_request(areq_id)
        if areq is None:
            raise InputError(f"unknown action request {areq_id}")
        if d not in ("YES", "NO", "MODIFY", "HOLD"):
            raise InputError(f"unknown decision {d!r}")
        kw = {"auth_context": ux.auth_context(areq, f.get("pin"), self.operator_pin, self.session_id, d, self.pin_gate)}
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
        try:
            o = self.store.record_outcome(item["item_id"], kind, **kw)
        except AlreadyClosed as ex:
            raise InputError(str(ex)) from None
        return f"Outcome {o['kind']} recorded ({o['outcome_id']})."

    author = "michael"  # the authenticated operator: set HERE, never taken from a form (F-14; all humans share one DB login)

    def add_note(self, item_id, f):
        """F-14: Michael's own model knowledge → spine_d.record_operator_note. Human channel only (R14): CSRF + PIN,
        and this is the only code path in the UI that calls it. Returns a flash message; raises with every reason."""
        self._check_csrf(f)
        if not self.operator_pin:
            raise InputError("step-up not configured (MBOS_OPERATOR_PIN unset); notes are refused (fail-closed)")
        self.pin_gate.check(f.get("pin"), self.operator_pin, "a PIN is required to enter a note (it identifies you as the author).")
        try:
            if item_id is not None:  # None = added from My notes, not from a card (F-45)
                self.store.opportunity_card(item_id)
        except ItemNotFound:
            raise InputError("unknown opportunity") from None
        if not NOTE_CATEGORIES:
            raise InputError("lane C's package (mbos_economics) is not installed; notes are unavailable")
        bundle = ux.parse_note(f, self.author, iso(utcnow()))
        note_id = self.store.record_operator_note(bundle)
        return f"Note saved ({note_id}). It will show on this model's cards as your recommendation."

    def set_tow(self, f):
        self.asset_gate(f)
        self.tow = deal_ui.parse_tow(f)

    def save_preset(self, f):
        self._check_csrf(f)
        name = " ".join(str(f.get("name") or "").split())[:40]
        if not name:
            raise InputError("a preset needs a name")
        flt, _ = deal_ui.parse_filters(f)
        if name not in self.presets and len(self.presets) >= 20:
            raise InputError("at most 20 presets; reuse a name to replace one")
        self.presets[name] = flt
        return name

    def asset_gate(self, f):
        """F-34: CSRF + step-up PIN for any owned-asset change; the author is the server-set operator (R14)."""
        self._check_csrf(f)
        if not self.operator_pin:
            raise InputError("step-up not configured (MBOS_OPERATOR_PIN unset); changes are refused (fail-closed)")
        self.pin_gate.check(f.get("pin"), self.operator_pin, "a PIN is required to change your assets (it identifies you as the owner).")

    def _numbers_gate(self, f):
        """CSRF + step-up PIN for any mission/capital change; the author is ALWAYS the server-set operator (R14)."""
        self._check_csrf(f)
        if not self.operator_pin:
            raise InputError("step-up not configured (MBOS_OPERATOR_PIN unset); changes are refused (fail-closed)")
        self.pin_gate.check(f.get("pin"), self.operator_pin, "a PIN is required to change your numbers (it identifies you as the owner).")
        nonce = f.get("nonce") or ""
        if not (8 <= len(nonce) <= 64 and nonce.isascii() and nonce.isalnum()):
            raise InputError("invalid form token; reload the page")
        return nonce

    def set_mission(self, f):
        """F-22: weekly target / hours / cash situation -> a receipted mission row. Blank = UNKNOWN."""
        from . import numbers_view

        nonce = self._numbers_gate(f)
        mission = numbers_view.parse_mission(f, utcnow())
        mid = self.store.set_mission(mission, self.author, "f22:mission:" + nonce)
        return f"Saved ({mid}); each blank value is UNKNOWN."

    def capital_move(self, f):
        """F-22: fund / withdraw -> mbos.capital_fund / capital_withdraw (owner channel, dry-run ledger)."""
        from . import numbers_view

        nonce = self._numbers_gate(f)
        kind = f.get("kind")
        if kind not in ("fund", "withdraw"):
            raise InputError("kind must be fund or withdraw")
        amt = numbers_view.parse_amount(f.get("amount"), "Amount", cap=numbers_view.MAX_USD, required=True, positive=True)
        key = f"f22:{kind}:{nonce}"
        def replay(seen):  # report what the receipt recorded, never what this request says (F-72)
            got = self.store.capital_recorded(seen)
            return (f"This form was already submitted: it is recorded as {kind.title()} of ${got:,.2f} (receipt {seen}). "
                    "Nothing new was added.")

        seen = self.store.capital_seen(kind, key)
        if seen:
            return replay(seen)
        if kind == "fund":
            have = ((self.store.my_numbers().get("ledger") or {}).get("protected_principal"))
            numbers_view.check_fund(amt, have, f.get("confirm"))
        from .backend import AlreadyRecorded

        try:
            rid = self.store.capital_move(kind, format(amt, "f"), self.author, key)
        except AlreadyRecorded:  # F-84: lost the double-submit race; the winner's receipt is the answer
            seen = self.store.capital_seen(kind, key)
            if seen:
                return replay(seen)
            raise InputError("this form was already submitted; reload the page") from None
        got = self.store.capital_recorded(rid)
        return f"{kind.title()} of ${got:,.2f} recorded (receipt {rid})."

    def _spine_campaigns(self) -> bool:
        """F-25: campaigns live on the spine when the DB has migration 0019; otherwise the local JSON file is the fallback."""
        sup = getattr(self.store, "campaigns_supported", None)
        return bool(sup and sup())

    def campaign_records(self) -> list[dict]:
        return self.store.campaign_records() if self._spine_campaigns() else self.campaigns.all()

    def _wanted_change_spine(self, f, cid, action, nonce):
        """F-25: create/pause/resume -> `mbos.set_campaign`, cancel -> `mbos.cancel_campaign`, as `human:<id>` (the approver login).
        Each is receipted in the same transaction; the database also refuses ASSISTED_DEAL/AUTOPILOT as ACTIVE (E-17 CHECK)."""
        from mbos.campaign import errors as campaign_errors

        from .backend import AlreadyRecorded, NumbersRefused

        key = f"f25:campaign:{action}:{cid or 'new'}:{nonce}"
        try:
            if action == "create":
                doc = wanted_view.parse_campaign(f, self.author, wanted_view.level_reasons(self.policy_path))
                errs = campaign_errors(doc)
                if errs:
                    raise InputError("; ".join(errs[:3]))
                # F-79: the store returns the STORED id (a replay returns the first submit's id, not this request's fresh one)
                stored = self.store.set_campaign(doc, self.author, "Michael created a Wanted campaign (" + doc["autonomy"]["level"] + ")", key)
                msg = f"Campaign created ({stored}). It watches and recommends only."
            elif action == "edit":
                rec = next((r for r in self.store.campaign_records() if (r.get("doc") or {}).get("campaign_id") == (cid or "")), None)
                if rec is None:
                    raise InputError("unknown campaign")
                if rec["doc"].get("status") not in ("ACTIVE", "PAUSED"):
                    raise InputError(f"cannot edit a {rec['doc'].get('status')} campaign")
                doc = wanted_view.parse_campaign(f, self.author, wanted_view.level_reasons(self.policy_path), rec["doc"])
                errs = campaign_errors(doc)
                if errs:
                    raise InputError("; ".join(errs[:3]))
                self.store.set_campaign(doc, self.author, "Michael edited a Wanted campaign (" + doc["autonomy"]["level"] + ")", key)
                msg = "Campaign changes saved (a new revision; the history keeps the old one)."
            else:
                rec = next((r for r in self.store.campaign_records() if (r.get("doc") or {}).get("campaign_id") == (cid or "")), None)
                if rec is None:
                    raise InputError("unknown campaign")
                st = rec["doc"].get("status")
                new = {"pause": ("ACTIVE", "PAUSED"), "resume": ("PAUSED", "ACTIVE"), "cancel": (("ACTIVE", "PAUSED"), "CANCELLED")}.get(action)
                if new is None or st not in ((new[0],) if isinstance(new[0], str) else new[0]):
                    raise InputError(f"cannot {action} a {st} campaign")
                intent = f"Michael set a Wanted campaign {st} to {new[1]} ({action})"
                if action == "cancel":
                    self.store.cancel_campaign(cid, self.author, intent, key)
                else:
                    nd = {**rec["doc"], "status": new[1]}
                    errs = campaign_errors(nd)
                    if errs:  # a stored campaign that does not validate is never revised
                        raise InputError("stored campaign is malformed: " + "; ".join(errs[:3]))
                    self.store.set_campaign(nd, self.author, intent, key)
                msg = f"Campaign {new[1].lower()}."
        except AlreadyRecorded:  # F-84: lost the double-submit race; say so from the winner's receipt
            rid = self.store.campaign_receipt(key)
            if rid:
                return f"This form was already submitted and is recorded (receipt {rid}). Nothing new was added."
            raise InputError("this form was already submitted; reload the page") from None
        except NumbersRefused as ex:
            raise InputError(str(ex)) from None
        rid = self.store.campaign_receipt(key)
        return msg + (f" Receipt {rid}." if rid else "")

    def wanted_change(self, f, cid=None, action="create"):
        """F-23: create / pause / resume / cancel a campaign. CSRF + PIN, server-set author. WATCH_ONLY/RECOMMEND only: a higher
        level is refused with the E-17 reason and nothing is stored. No contact is ever made."""
        from mbos.campaign import errors as campaign_errors
        from mbos.clock import iso

        nonce = self._numbers_gate(f)
        now = iso(utcnow())
        if self._spine_campaigns():
            return self._wanted_change_spine(f, cid, action, nonce)
        if action == "create":
            doc = wanted_view.parse_campaign(f, self.author, wanted_view.level_reasons(self.policy_path))
            errs = campaign_errors(doc)
            if errs:
                raise InputError("; ".join(errs[:3]))
            self.campaigns.put(doc, self.author, "created (" + doc["autonomy"]["level"] + ")", now)
            return f"Campaign created ({doc['campaign_id']}). It watches and recommends only."
        rec = self.campaigns.get(cid or "")
        if rec is None:
            raise InputError("unknown campaign")
        doc, st = rec["doc"], rec["doc"]["status"]
        if action == "edit":
            if st not in ("ACTIVE", "PAUSED"):
                raise InputError(f"cannot edit a {st} campaign")
            nd = wanted_view.parse_campaign(f, self.author, wanted_view.level_reasons(self.policy_path), doc)
            errs = campaign_errors(nd)
            if errs:
                raise InputError("; ".join(errs[:3]))
            self.campaigns.put(nd, self.author, "edited (" + nd["autonomy"]["level"] + ")", now)
            return "Campaign changes saved."
        new = {"pause": ("ACTIVE", "PAUSED"), "resume": ("PAUSED", "ACTIVE"), "cancel": (("ACTIVE", "PAUSED"), "CANCELLED")}.get(action)
        if new is None or st not in ((new[0],) if isinstance(new[0], str) else new[0]):
            raise InputError(f"cannot {action} a {st} campaign")
        doc = {**doc, "status": new[1]}
        self.campaigns.put(doc, self.author, f"{action} ({st} to {new[1]})", now)
        return f"Campaign {new[1].lower()}."

    def add_comp(self, item_id, f):
        """F-28: "Add a price I saw". CSRF + PIN (human channel); the author is server-set. Writes one ManualCompsAdapter inbox file."""
        nonce = self._numbers_gate(f)
        item = self.store.item(item_id)
        if item is None:
            raise InputError("unknown opportunity")
        if item.get("state") != "RESEARCHING":
            raise InputError("this item is not waiting for a price")
        doc = comps_view.parse_comp({**f, "nonce": nonce}, item, self.author, utcnow())
        _, created = comps_view.write_comp(self.comps_inbox, doc)
        return comps_view.saved_message(item_id, created, doc.get("condition"))

    def add_attestation(self, item_id, f):
        """F-90: "Confirm" one requested evidence key -> `record_attestation` (owner channel). CSRF + PIN; the author is server-set;
        only a key the engine requested on this item (and a person can attest) is accepted."""
        self._numbers_gate(f)
        item = self.store.item(item_id)
        if item is None:
            raise InputError("unknown opportunity")
        key = (f.get("key") or "").strip()
        if key not in attest_view.requested_keys(item):
            raise InputError("that evidence was not requested for this item (or is already confirmed)")
        self.store.record_attestation(item_id, key, attest_view.parse_note(f.get("note")), self.author)
        return (f"Confirmed: {key}. Your word is recorded (human, receipted). "
                f"The worker will re-check this item with it (about a minute); reload to see the result. "
                f"If no worker is running, run `mbos recheck {item_id}` on the server.")

    def _human_input(self, item_id, f, which):
        """F-32: shared gate for "Set my quote" / "Tell me about the job": CSRF + PIN, the item must exist and the form must apply to it."""
        self._numbers_gate(f)
        item = self.store.item(item_id)
        if item is None:
            raise InputError("unknown opportunity")
        if item.get("state") in inputs_view.DONE_STATES:
            raise InputError("this item is finished; nothing more can be recorded on it")
        if which == "quote":
            if item.get("type") != "service":
                raise InputError("a quote applies to a service lead only")
            return item, inputs_view.parse_quote(f)
        card = self.store.opportunity_card(item_id)["card"]
        if not inputs_view.needs_scope(card):
            raise InputError("the system is not waiting on a scope for this item")
        return item, inputs_view.parse_scope(f, item)

    def set_quote(self, item_id, f):
        """F-32: "Set my quote" -> `record_human_input(kind=quote)` (owner channel)."""
        _, (inputs, note) = self._human_input(item_id, f, "quote")
        self.store.record_human_inputs(item_id, inputs, note, self.author)
        return inputs_view.saved_message(f"your quote of ${inputs[0][2]:,}", item_id)

    def set_scope(self, item_id, f):
        """F-32: "Tell me about the job" -> `record_human_input(kind=scope_override)` per field (owner channel, one transaction)."""
        _, (inputs, note) = self._human_input(item_id, f, "scope")
        self.store.record_human_inputs(item_id, inputs, note, self.author)
        return inputs_view.saved_message(f"what you know about the job ({len(inputs)} figures)", item_id)

    def record_bought(self, item_id, f):
        """F-33: "I bought it" -> D-31 `record_acquisition` (owner channel; capital deploys when HE records it)."""
        nonce = self._numbers_gate(f)
        item = self.store.item(item_id)
        if item is None:
            raise InputError("unknown opportunity")
        if item.get("type") != "flip" or item.get("state") not in bought_view.BUY_STATES:
            raise InputError("a purchase is recorded on a flip you have said YES to (approved or acted), not on this item")
        amount, note = bought_view.parse_bought(f)
        try:
            self.store.record_acquisition(item_id, amount, note, self.author, f"{item_id}:bought:{nonce}")
        except NumbersRefused as ex:
            raise InputError("; ".join(ex.reasons)) from None
        return bought_view.saved_message(amount, self.store.capital_for(item_id))

    def add_followup(self, item_id, f):
        """F-11: draft a follow-up / offer / quote as its OWN request via the public API (A-15). CSRF, human channel. It only
        proposes: the YES (and the PIN for binding actions) is Michael's separate decision."""
        self._check_csrf(f)
        item = self.store.item(item_id)
        if item is None:
            raise InputError("unknown opportunity")
        pa = ux.build_followup(item, f, self.store.asked_question_ids(item_id))
        out = self.store.propose_followup(item_id, pa)
        if out.get("policy_denied") or not out.get("action_request_id"):
            raise FollowupRefused(["blocked by policy: no agent may propose that action, or the policy check denied it. Nothing was created."])
        kind = {"followup": "Follow-up questions", "offer": "Offer", "quote": "Quote"}[f.get("kind")]
        return f"{kind} drafted ({out['action_request_id']}). It is waiting for your YES below; nothing has been sent."

    def _note_gate(self, f):
        """CSRF + step-up PIN for any note change; the author is ALWAYS the server-set operator."""
        self._check_csrf(f)
        if not self.operator_pin:
            raise InputError("step-up not configured (MBOS_OPERATOR_PIN unset); note changes are refused (fail-closed)")
        self.pin_gate.check(f.get("pin"), self.operator_pin, "a PIN is required to change a note (it identifies you as the author).")

    def _head(self, note_id):
        n = next((x for x in self.store.operator_notes(include_retracted=True) if x["note_id"] == note_id), None)
        if n is None:
            raise InputError("that note is not the current version (it was edited or retracted); reload the page")
        if n.get("retracted"):
            raise InputError("that note is retracted; add a new note instead")
        return n

    def edit_note(self, note_id, f):
        """F-16: an edit is a NEW note with `supersedes` = the current head. Nothing is overwritten."""
        self._note_gate(f)
        self._head(note_id)
        bundle = ux.parse_note(f, self.author, iso(utcnow()), supersedes=note_id)
        new_id = self.store.record_operator_note(bundle)
        return f"Note edited: new version {new_id} replaces {note_id}. The old version stays in the history."

    def retract_note(self, note_id, f):
        """F-16: retract the head of the chain via spine_d.retract_operator_note; a reason is required."""
        self._note_gate(f)
        self._head(note_id)
        reason = (f.get("reason") or "").strip()
        if not reason:
            raise InputError("a retraction needs a reason")
        rid = self.store.retract_operator_note(note_id, self.author, iso(utcnow()), reason[:300])
        return f"Note retracted ({rid}). It no longer shows on cards; the history keeps it."

    def check_view(self, f):
        """F-19: lint Michael's edited wording against the inventory. Read-only: it only LINTS and never publishes."""
        from . import merch, merch_view

        self._check_csrf(f)
        loaded = merch_view.load_inventory(self.inventory_file)
        if loaded["doc"] is None or loaded["errors"]:
            raise InputError("; ".join(loaded["errors"]) or "no inventory")
        inv, audience = loaded["doc"], f.get("audience")
        if audience not in merch.AUDIENCES:
            raise InputError(f"unknown audience {audience!r}")
        keep = set(f.get("_disclose", []))  # ticked disclosure checkboxes; an unticked defect is DROPPED so the lint can refuse it
        dropped = [d["id"] for d in inv["defects"] if d["id"] not in keep]
        view = merch.build_view(inv, audience, headline=f.get("headline", ""), body=f.get("body", ""),
                                call_to_action=f.get("call_to_action", ""), drop_disclosures=dropped)
        return {"audience": audience, "headline": view["headline"], "body": view["body"], "call_to_action": view["call_to_action"],
                "dropped": dropped, "reasons": merch.check_view(inv, view)}

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

        def _redirect(self, loc):
            self.send_response(303)
            self.send_header("Location", loc)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send(self, status, body, ctype="text/html; charset=utf-8", headers=None):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; img-src https: http:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
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
            _CUR.path = u.path
            qs = parse_qs(u.query)
            now = utcnow()
            flash = (qs.get("msg") or [None])[0]
            err = (qs.get("err") or [None])[0]
            if u.path == "/" and not u.query:  # F-48: the default landing is Michael's Marketplace; the old queue is /queue
                return self._redirect("/market")
            if u.path == "/":
                return self._redirect("/queue?" + u.query)
            if u.path == "/queue":
                from . import mission_view

                try:
                    lv = landing_fix.live_only(mission_view.load_live(app.store, now, app.mission_file), app.store)
                    head = mission_view.today_header(lv, None, self._leg_states(lv))
                except Exception as ex:  # noqa: BLE001 - Today must still render; say the header is unavailable
                    head = f"<div class='card'><p class='bad'>Today's header is unavailable ({e(type(ex).__name__)}).</p></div>"
                st = app.state()
                demo = (qs.get("demo") or [""])[0] == "1"  # F-46: training items only behind the DEMO switch
                q, dq = live_demo.split_queue(app.store, views.queue(app.store, now))
                n_hidden = sum(len(v) for v in dq.values())
                parked = [(it, g) for it, g in self._parked() if not live_demo.is_demo(it)]
                try:  # F-38: the glanceable top; the full queue below is unchanged
                    gl = glance_view.build(app.store, now, parked, st)
                    keep = lambda r: not live_demo.is_demo(app.store.item(r["item_id"]))  # noqa: E731
                    for k in ("opportunities", "done", "working"):
                        gl[k] = [o for o in gl[k] if keep(o)]
                    gl["next"] = gl["next"] if gl["next"] is None or keep({"item_id": gl["next"]["href"].rsplit("/", 1)[-1]}) else None
                    glance = glance_view.render(gl, app.csrf)
                except Exception as ex:  # noqa: BLE001 - Today must still render
                    glance = f"<div class='card'><p class='bad'>At-a-glance cards are unavailable ({e(type(ex).__name__)}).</p></div>"
                try:  # F-39: asset deals first
                    cards = [resale_view.decide(d) for d in app.deals.values()] if demo else []
                    deals = (resale_view.control_strip(app.resale, cards, len(q["pending"])) +
                             resale_view.render_hunt(cards, resale_view.changes(app.resale, cards), full=False)) if demo else ""
                    deals = deals
                except Exception as ex:  # noqa: BLE001 - Today must still render
                    deals = f"<div class='card'><p class='bad'>Asset deals are unavailable ({e(type(ex).__name__)}).</p></div>"
                n_hidden += len(app.deals)
                sw = live_demo.hidden_note(n_hidden, False)
                demo_sec = ""
                if demo:  # the same glance cards, but only for demo items and only inside the banner section
                    try:
                        dg = glance_view.build(app.store, now, [(it, g) for it, g in self._parked() if live_demo.is_demo(it)], st)
                        for k in ("opportunities", "done", "working"):
                            dg[k] = [o for o in dg[k] if live_demo.is_demo(app.store.item(o["item_id"]))]
                        dg["next"], dg["blocked"] = None, [x for x in dg["blocked"] if x.get("item_id") and live_demo.is_demo(app.store.item(x["item_id"]))]
                        dglance = glance_view.render(dg, app.csrf)
                    except Exception as ex:  # noqa: BLE001
                        dglance = f"<p class='bad'>Demo cards unavailable ({e(type(ex).__name__)}).</p>"
                    demo_sec = live_demo.render_demo_section(dq, deals + dglance)
                return self._send(200, page("Operator queue", sw + glance + head + comps_view.render_today(parked)
                                            + f"<details><summary><b>Full queue</b></summary>{render_queue(q)}</details>" + demo_sec,
                                            st, flash or err, bool(err)))
            if u.path == "/digest":
                from . import digest as digest_view

                return self._send(200, page("Morning digest", render_digest(digest_view.build(landing_fix.LiveStore(app.store), iso(now))), app.state()))
            if u.path == "/notes":
                return self._notes_page(flash or err, bool(err))
            if u.path.startswith("/item/"):
                return self._item_page(u.path.split("/")[2], now, flash or err, bool(err))
            if u.path == "/mission":
                from . import mission_view

                loaded = landing_fix.live_only(mission_view.load_live(app.store, now, app.mission_file), app.store)  # F-49: no demo legs
                known = {l["item_id"] for l in (loaded["doc"] or {}).get("legs", []) if app.store.item(l["item_id"])} if loaded["kind"] == "plan" else set()
                ids = {l["item_id"] for l in (loaded["doc"] or {}).get("legs", [])} | set((loaded["doc"] or {}).get("replace_if_stale") or []) if loaded["kind"] == "plan" else set()
                titles = {i: ((app.store.item(i) or {}).get("normalized") or {}).get("title") for i in ids}
                return self._send(200, page("Weekly mission", mission_view.render_page(loaded, known, {k: v for k, v in titles.items() if v}, self._leg_states(loaded))
                                                                + bought_view.render_open_flips(app.store.open_acquisitions()), app.state()))
            if u.path == "/demo":  # F-51: the only door to demo/training data, deliberately not in NAV
                return self._send(200, page("Demo / training data", live_demo.DEMO_PAGE, app.state()))
            if u.path == "/market":
                return self._send(200, page("Michael's Marketplace", market_routes.page_body(app, qs, now), app.state(), flash))
            if u.path == "/wanted":
                return self._wanted_page(flash or err, bool(err))
            if u.path == "/numbers":
                return self._numbers_page(flash or err, bool(err))
            if u.path == "/usage":
                from . import usage_view

                return self._send(200, page("Usage and agents", usage_view.render_page(usage_view.load(app.telemetry_dir), usage_view.queue_states(app.queue_file)), app.state()))
            if u.path == "/assets" or (u.path.startswith("/assets/") and u.path.split("/")[2] in app.assets):
                return self._assets_page(u.path.split("/")[2] if u.path != "/assets" else None, flash or err, bool(err))
            if u.path == "/resale":
                return self._resale_page(now, flash or err, bool(err), qs)
            if u.path == "/owner-listing":
                return self._send(200, page("Add a listing", live_demo.render_owner_form(app.csrf) + "".join(
                    live_demo.render_owner_listing(d) for d in app.owner_listings.values()), app.state()))
            if u.path == "/gsa":
                lots = live_demo.load_gsa_lots(os.environ.get("MBOS_GSA_LOTS_FILE"))
                return self._send(200, page("GSA lots", "".join(live_demo.render_gsa_lot(x) for x in lots) or
                                            "<div class='card'><p>No GSA lots on file (none fetched yet). Nothing is shown rather than guessed.</p></div>", app.state()))
            if u.path == "/intake":
                from . import intake_view

                return self._send(200, page("Intake", intake_view.render_start(app.csrf), app.state()))
            if u.path.startswith("/intake/") and u.path.split("/")[2] in app.intake_drafts:
                from . import intake_view

                iid = u.path.split("/")[2]
                return self._send(200, page("Intake", intake_view.render_draft(iid, app.intake_drafts[iid], app.csrf), app.state()))
            if u.path == "/preview":
                from . import merch_view

                return self._send(200, page("Audience previews", merch_view.render_page(merch_view.load_inventory(app.inventory_file), app.csrf), app.state()))
            if u.path == "/summary":
                from . import summary as summary_view

                s_ = summary_view.build_summary(landing_fix.LiveStore(app.store), now, health_file=app.health_file)
                return self._send(200, page("Daily summary", "<div class='card'>" + summary_view.render_html_body(s_) +
                                            "<p class='small mut'>Files on disk: <code>python -m operator_ui summary --out-dir DIR</code>"
                                            " (local only; never sent).</p></div>", app.state()))
            if u.path.startswith("/provenance/"):
                pid = u.path.split("/")[2]
                return self._send(200, page("Provenance", render_provenance(app.store.provenance(pid), pid), app.state()))
            if u.path == "/holds":
                return self._send(200, page("HOLD backlog", render_holds(landing_fix.LiveStore(app.store).held(), now), app.state()))
            if u.path == "/sources":
                return self._send(200, page("Source health", render_sources(load_health(app.health_file), now), app.state()))
            if u.path == "/outcomes":
                return self._send(200, page("Outcomes", render_outcomes(landing_fix.LiveStore(app.store).outcomes(), app.store), app.state()))
            if u.path == "/ledger":
                return self._send(200, page("Receipt ledger", render_ledger(landing_fix.LiveStore(app.store)), app.state()))
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

        def _resale_page(self, now, flash=None, is_err=False, qs=None):
            qs = qs or {}
            demo = (qs.get("demo") or [""])[0] == "1"
            cards = [resale_view.decide(d) for d in app.deals.values()] if demo else []  # F-46: DEMO lots only behind the switch
            realized = {}
            for it in app.resale.items.values():
                if it["stage"] == "sold" and it["deal_id"]:
                    realized[it["deal_id"]] = {"net": it["sale"]["net"], "label": resale_view.sale_label(it)}
            preset = (qs.get("preset") or [None])[0]
            flt, warn = (dict(app.presets[preset]), []) if preset in app.presets else deal_ui.parse_filters(qs)
            kept, out = deal_ui.apply_filters(cards, flt, app.tow)
            body = ((live_demo.BANNER + live_demo.hidden_note(0, True) if demo else live_demo.hidden_note(len(app.deals), False))
                    + resale_view.control_strip(app.resale, cards, len(views.queue(app.store, now))) + deal_ui.render_milestones()
                    + deal_ui.render_filters(flt, app.presets, app.csrf, preset if preset in app.presets else None, warn, len(cards), len(kept), bool(qs.get("find")))
                    + deal_ui.render_tow(app.tow, app.csrf, bool(app.operator_pin)) + deal_ui.render_filtered_out(out)
                    + resale_view.render_hunt(kept, resale_view.changes(app.resale, cards), full=False)
                    + "".join(deal_ui.render_deal(c, resale_view.proof_html(c, realized.get(c["id"])), app.tow) for c in resale_view.rank(kept))
                    + "".join(f"<div id='out-{e(c['id'])}'></div>" for c, _ in out)
                    + resale_view.render_workflow(app.resale, cards, app.csrf, bool(app.operator_pin)))
            return self._send(200, page("Resale", body, app.state(), flash, is_err))

        def _post_deal_settings(self, which):
            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True).items()}
            try:
                if which == "tow":
                    app.set_tow(f)
                    msg, loc = "Tow vehicle and limits saved.", "/resale?msg="
                else:
                    name = app.save_preset(f)
                    msg, loc = f"Preset '{name}' saved (kept in memory).", f"/resale?preset={quote(name)}&msg="
            except (InputError, ValueError) as ex:
                return self._resale_page(utcnow(), str(ex), True)
            self.send_response(303)
            self.send_header("Location", loc + quote(msg))
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _post_resale(self, parts):
            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True).items()}
            try:
                app.asset_gate(f)
                if parts[1] == "add":
                    deal = f.get("deal") or None
                    net = next((c["net"] for c in map(resale_view.decide, app.deals.values()) if c["id"] == deal), None)
                    app.resale.intake(f, app.author, deal, net)
                else:
                    app.resale.advance(parts[1], f, app.author)
            except Exception as ex:  # InputError, ResaleError: shown, nothing recorded
                return self._resale_page(utcnow(), str(ex), True)
            self.send_response(303)
            self.send_header("Location", f"/resale?msg={quote('Recorded with a receipt (DRY-RUN). Nothing was published, sent or spent.')}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _assets_page(self, aid, flash=None, is_err=False, vals=None, bad=None):
            from . import assets_view

            if aid is None:
                body = assets_view.render_list(app.assets, app.csrf, bool(app.operator_pin), vals=vals, bad=bad)
                return self._send(200, page("My assets", body, app.state(), flash, is_err))
            d = app.assets[aid]
            body = assets_view.render_card(aid, d, assets_view.compare(aid, d, app.author), app.csrf, bool(app.operator_pin), vals=vals, bad=bad)
            return self._send(200, page(d.get("title") or "Asset", body, app.state(), flash, is_err))

        def _post_assets(self, parts):
            from . import assets_view

            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True).items()}
            aid = parts[1] if len(parts) == 3 else None
            if aid is not None and aid not in app.assets:
                return self._send(404, page("Not found", "<p>No such asset.</p>", app.state()))
            try:
                app.asset_gate(f)
                if aid is None:
                    aid, d = assets_view.new_id(), assets_view.add(f.get("title", ""), f)
                else:
                    d = assets_view.apply_answers(app.assets[aid], f)
            except Exception as ex:  # InputError, ValueError, ContractViolation: shown, nothing recorded
                kept = {k: v for k, v in f.items() if k not in ("pin", "csrf")}  # F-134: keep what he typed, mark the bad box
                return self._assets_page(None if len(parts) == 2 else aid, str(ex), True, kept, getattr(ex, "fields", None))
            app.assets[aid] = d
            self.send_response(303)
            self.send_header("Location", f"/assets/{aid}?msg={quote('Saved (DRY-RUN). Nothing is marked verified.')}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _post_intake(self, parts):
            from . import intake_view

            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True).items()}
            try:
                app._check_csrf(f)
                if parts == ["intake", "start"]:
                    iid, d = intake_view.new_id(), intake_view.start(f.get("text", "")[:500])
                else:
                    iid = parts[1]
                    if iid not in app.intake_drafts:
                        return self._send(404, page("Not found", "<p>No such draft.</p>", app.state()))
                    d = intake_view.apply_answers(app.intake_drafts[iid], f)
            except Exception as ex:  # InputError, ValueError, ContractViolation: shown, nothing recorded
                return self._send(200, page("Intake", intake_view.render_start(app.csrf, f"<div class='flash err'>{e(ex)}</div>"), app.state()))
            app.intake_drafts[iid] = d
            return self._send(200, page("Intake", intake_view.render_draft(iid, d, app.csrf), app.state()))

        def _post_preview_check(self):
            from . import merch_view

            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            raw = parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True)
            f = {k: v[0] for k, v in raw.items()}
            f["_disclose"] = raw.get("disclose", [])  # a checkbox group: every ticked defect id
            try:
                result = app.check_view(f)
            except InputError as ex:
                return self._send(200, page("Audience previews", f"<div class='flash err'>{e(ex)}</div>", app.state()))
            return self._send(200, page("Audience previews", merch_view.render_page(merch_view.load_inventory(app.inventory_file), app.csrf, result), app.state()))

        def _notes_page(self, flash=None, is_err=False, reasons=None):
            notes = app.store.operator_notes(include_retracted=True)
            return self._send(200, page("My notes", render_notes(notes, app.store.lane, app.csrf, reasons), app.state(), flash, is_err))

        def _numbers_page(self, flash=None, is_err=False, reasons=None, values=None):
            from . import numbers_view

            body = numbers_view.render_page(app.store.my_numbers(), app.csrf, bool(app.operator_pin), reasons, values,
                                            (app.pin_gate.remaining() + 59) // 60)
            return self._send(200, page("My numbers", body, app.state(), flash, is_err))

        def _post_numbers(self, which):
            """F-22: mission or capital change. CSRF + PIN; the author is server-set (R14)."""
            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True).items()}
            try:
                msg = app.set_mission(f) if which == "mission" else app.capital_move(f)
            except NumbersRefused as ex:
                return self._numbers_page(reasons=ex.reasons, values={k: v for k, v in f.items() if k not in ("pin", "csrf")})
            except InputError as ex:
                return self._numbers_page(reasons=[str(ex)], values={k: v for k, v in f.items() if k not in ("pin", "csrf")})
            self.send_response(303)
            self.send_header("Location", f"/numbers?msg={quote(msg)}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _wanted_page(self, flash=None, is_err=False, errors=None, values=None):
            now = utcnow()
            items = app.store.items_in_states(wanted_view.OPEN_STATES)
            body = wanted_view.render_page(app.campaign_records(), items, now, app.csrf, bool(app.operator_pin),
                                           wanted_view.level_reasons(app.policy_path), errors, values)
            return self._send(200, page("Wanted", body, app.state(), flash, is_err))

        def _post_wanted(self, cid, action):
            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True).items()}
            try:
                msg = app.wanted_change(f, cid, action)
            except InputError as ex:
                return self._wanted_page(errors=[str(ex)], values={k: v for k, v in f.items() if k not in ("pin", "csrf")})
            self.send_response(303)
            self.send_header("Location", f"/wanted?msg={quote(msg)}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _post_note_change(self, note_id, action):
            """F-16: edit (new version) or retract. CSRF + PIN; the author is server-set (R14)."""
            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True).items()}
            try:
                msg = app.add_note(None, f) if action == "add" else app.edit_note(note_id, f) if action == "edit" else app.retract_note(note_id, f)
            except (ux.NoteInputError, NoteRefused) as ex:
                return self._notes_page(reasons=ex.reasons)
            except InputError as ex:
                return self._notes_page(reasons=[str(ex)])
            self.send_response(303)
            self.send_header("Location", f"/notes?msg={quote(msg)}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _post_followup(self, item_id):
            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True).items()}
            try:
                msg = app.add_followup(item_id, f)
            except (FollowupRefused, InputError, DecisionRefused) as ex:
                reasons = ex.reasons if hasattr(ex, "reasons") else [str(ex)]
                return self._item_page(item_id, utcnow(), None, False, followup_reasons=reasons,
                                       followup_values={k: v for k, v in f.items() if k != "csrf"})
            self.send_response(303)
            self.send_header("Location", f"/item/{item_id}?msg={quote(msg)}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _leg_states(self, loaded):
            """F-121/F-122: the live state of each plan leg's item, so the page never calls a held or executed job 'ready for your YES'."""
            if loaded.get("kind") != "plan":
                return {}
            out = {}
            for l in (loaded.get("doc") or {}).get("legs") or []:
                try:
                    out[l["item_id"]] = (app.store.item(l["item_id"]) or {}).get("state")
                except Exception:  # noqa: BLE001 - a missing state just leaves the plan's own verdict in force
                    pass
            return out

        def _parked(self):
            """F-28: [(item, gap text)] for Items in RESEARCHING, for the "Needs from you" block on the queue."""
            out = []
            for it in app.store.items_in_states(("RESEARCHING",)):
                try:
                    gap = comps_view.gap_text(app.store.opportunity_card(it["item_id"])["card"])
                except Exception:  # noqa: BLE001 - the list must render even when a card cannot be built
                    gap = comps_view.DEFAULT_GAP
                out.append((it, gap))
            return out

        def _post_comp(self, item_id):
            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True).items()}
            try:
                msg = app.add_comp(item_id, f)
            except (comps_view.CompRefused, InputError) as ex:
                return self._item_page(item_id, utcnow(), None, False, comp_reasons=getattr(ex, "reasons", None) or [str(ex)],
                                       comp_values={k: v for k, v in f.items() if k not in ("pin", "csrf")})
            self.send_response(303)
            self.send_header("Location", f"/item/{item_id}?msg={quote(msg)}#needs")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _post_attest(self, item_id):
            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True).items()}
            try:
                msg = app.add_attestation(item_id, f)
            except (InputError, NumbersRefused) as ex:
                return self._item_page(item_id, utcnow(), None, False, attest_reasons=getattr(ex, "reasons", None) or [str(ex)])
            self.send_response(303)
            self.send_header("Location", f"/item/{item_id}?msg={quote(msg)}#confirm")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _post_input(self, item_id, which):
            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True).items()}
            try:
                msg = (app.set_quote if which == "quote" else app.set_scope)(item_id, f)
            except (InputError, NumbersRefused) as ex:
                return self._item_page(item_id, utcnow(), None, False, input_reasons=getattr(ex, "reasons", None) or [str(ex)],
                                       input_which=which, input_values={k: v for k, v in f.items() if k not in ("pin", "csrf")})
            self.send_response(303)
            self.send_header("Location", f"/item/{item_id}?msg={quote(msg)}#{which}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _post_bought(self, item_id):
            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True).items()}
            try:
                msg = app.record_bought(item_id, f)
            except (InputError, NumbersRefused) as ex:
                return self._item_page(item_id, utcnow(), None, False, bought_reasons=getattr(ex, "reasons", None) or [str(ex)],
                                       bought_values={k: v for k, v in f.items() if k not in ("pin", "csrf")})
            self.send_response(303)
            self.send_header("Location", f"/item/{item_id}?msg={quote(msg)}#bought")
            self.send_header("Content-Length", "0")
            self.end_headers()

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

        def _item_page(self, item_id, now, flash, is_err, note_reasons=None, note_values=None, followup_reasons=None,
                       followup_values=None, comp_reasons=None, comp_values=None, attest_reasons=None, input_reasons=None, input_which=None, input_values=None,
                       bought_reasons=None, bought_values=None):
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
            store_item = app.store.item(item_id) or {}
            if live_demo.is_demo(store_item):  # F-46: never present a training item as real
                body = live_demo.BANNER + body
            body = comps_view.render_needs(card, store_item.get("state", "?"), app.csrf, bool(app.operator_pin),
                                           bool(app.comps_inbox), comp_reasons, comp_values, secrets.token_hex(8),
                                           lane=store_item.get("type"), parts_only=comps_view.parts_only(app.comps_inbox, item_id)) + body
            body = attest_view.render_confirm(store_item, app.csrf, bool(app.operator_pin), app.store.lane == "lane_d",
                                              secrets.token_hex(6), attest_reasons) + body
            body = bought_view.render_bought(store_item, app.store.capital_for(item_id), app.csrf, bool(app.operator_pin),
                                             app.store.lane == "lane_d", secrets.token_hex(6), bought_reasons, bought_values) + body
            body = inputs_view.render_inputs(store_item, card, app.csrf, bool(app.operator_pin), app.store.lane == "lane_d",
                                             secrets.token_hex(6), input_reasons, input_which, input_values) + body
            body += card_view.render_followup_section(card, (app.store.item(item_id) or {}).get("state", "?"), app.csrf,
                                                      app.store.lane == "lane_d", open_areq is not None,
                                                      flash_reasons=followup_reasons, values=followup_values)
            body += card_view.render_note_section(card, app.csrf, app.store.lane == "lane_d", sorted(NOTE_CATEGORIES), sorted(NOTE_KINDS),
                                                  ux.NOTE_BASIS_CHOICES, flash_reasons=note_reasons, values=note_values)
            body += render_outcome_card_section(app, item_id, open_areq, res["areqs"])
            return self._send(200, page(card["item"]["title"], body, app.state(), flash, is_err))

        def do_POST(self):
            if not self._host_ok():
                return
            u = urlparse(self.path)
            parts = u.path.strip("/").split("/")
            _CUR.path = u.path
            if parts in (["resale", "tow"], ["resale", "preset"]):
                return self._post_deal_settings(parts[1])
            if parts == ["notes", "add"]:
                return self._post_note_change(None, "add")
            if parts == ["resale", "add"] or (len(parts) == 3 and parts[0] == "resale" and parts[2] == "advance"):
                return self._post_resale(parts[:2] if parts[1] == "add" else [parts[0], parts[1]])
            if parts == ["assets", "add"] or (len(parts) == 3 and parts[0] == "assets" and parts[2] == "answer"):
                return self._post_assets(parts)
            if parts == ["owner-listing"]:
                n = min(int(self.headers.get("Content-Length") or 0), 65536)
                f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True).items()}
                try:
                    app._check_csrf(f)
                    d = live_demo.parse_owner_listing(f, app.author, iso(utcnow()))
                except Exception as ex:  # shown, nothing recorded
                    return self._send(200, page("Add a listing", live_demo.render_owner_form(app.csrf, f"<div class='flash err'>{e(ex)}</div>"), app.state()))
                app.owner_listings[secrets.token_hex(4)] = d
                return self._send(200, page("Add a listing", live_demo.render_owner_form(app.csrf) + "".join(
                    live_demo.render_owner_listing(x) for x in app.owner_listings.values()), app.state()))
            if parts == ["intake", "start"] or (len(parts) == 3 and parts[0] == "intake" and parts[2] == "answer"):
                return self._post_intake(parts)
            if len(parts) == 2 and parts[0] == "numbers" and parts[1] in ("mission", "capital"):
                return self._post_numbers(parts[1])
            if parts[0] == "market" and len(parts) in (2, 3):
                n = min(int(self.headers.get("Content-Length") or 0), 65536)
                f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True).items()}
                loc, errs = market_routes.post(app, parts, f)
                if errs:
                    return self._send(200, page("Michael's Marketplace", market_routes.page_body(app, {}, utcnow(), errs, {k: v for k, v in f.items() if k not in ("pin", "csrf")}), app.state()))
                self.send_response(303)
                self.send_header("Location", loc)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if parts == ["wanted", "create"]:
                return self._post_wanted(None, "create")
            if len(parts) == 3 and parts[0] == "wanted" and parts[2] in ("pause", "resume", "cancel", "edit"):
                return self._post_wanted(parts[1], parts[2])
            if parts == ["preview", "check"]:
                return self._post_preview_check()
            if len(parts) == 3 and parts[0] == "notes" and parts[2] in ("edit", "retract"):
                return self._post_note_change(parts[1], parts[2])
            if len(parts) == 3 and parts[0] == "item" and parts[2] == "comp":
                return self._post_comp(parts[1])
            if len(parts) == 3 and parts[0] == "item" and parts[2] == "attest":
                return self._post_attest(parts[1])
            if len(parts) == 3 and parts[0] == "item" and parts[2] in ("quote", "scope"):
                return self._post_input(parts[1], parts[2])
            if len(parts) == 3 and parts[0] == "item" and parts[2] == "bought":
                return self._post_bought(parts[1])
            if len(parts) == 3 and parts[0] == "item" and parts[2] == "note":
                return self._post_note(parts[1])
            if len(parts) == 3 and parts[0] == "item" and parts[2] == "followup":
                return self._post_followup(parts[1])
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
