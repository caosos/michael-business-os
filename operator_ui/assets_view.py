"""F-34: "My assets". An owned asset (the BBQ trailer) is added from the owned-trailer intake spec (A-45); photo references and the
inspection checklist keep each answer's basis (`verified` is not assignable: intake refuses it); the five-path comparison from
C-30 (`mbos_economics.owned_asset.compare_paths`) is shown as an opportunity card with every UNKNOWN named.
Owner channel (CSRF + PIN, server-set author). DRY-RUN: in-memory drafts, nothing is published, sent or spent.
"""

from __future__ import annotations

import hashlib
import html
import re
import secrets
from datetime import datetime, timezone

from mbos import intake

SPEC = "owned_trailer"
CHECKLIST = ("tires", "burners_work", "structure", "suspension", "hubs_bearings", "lights_wiring", "title_registration", "rework_needed")
_SAFETY_ENGINE = {"tires", "burners_work", "structure", "suspension", "hubs_bearings", "lights_wiring"}
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_ENGINE_BASIS = {"seller_stated": "FACT", "system_inferred": "INFER"}  # FACT = "stated by Michael"; never verified
e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731


def new_id() -> str:
    return "asset-" + secrets.token_hex(4)


def add(title: str, form: dict) -> dict:
    """A new owned-asset draft from the spec. Everything Michael types is `seller_stated`; a blank stays unanswered."""
    title = (title or "").strip()
    if not title:
        raise ValueError("give the asset a name (for example: BBQ trailer)")
    d = intake.new_draft(SPEC)
    d["title"] = title[:120]
    return apply_answers(d, form)


def apply_answers(d: dict, form: dict) -> dict:
    """`a_<key>` text with `b_<key>` basis (stated | inferred | unknown); `p_photo` adds photo references (one per line).
    A basis of `verified` (or anything else) is refused by intake."""
    for k, v in form.items():
        if not k.startswith("a_") or not v.strip():
            continue
        key, basis = k[2:], {"": "seller_stated", "stated": "seller_stated", "inferred": "system_inferred", "unknown": "UNKNOWN"}.get(
            form.get("b_" + k[2:], ""), form.get("b_" + k[2:]))
        d = intake.answer(d, key, v.strip()[:500], basis)
    for ref in (form.get("p_photo") or "").splitlines():
        if ref.strip():
            d = dict(d, evidence=d["evidence"] + [{"kind": "photo", "ref": ref.strip()[:300]}])  # a reference, still unverified
    return d


def _rng(text):
    n = [float(x.replace(",", "")) for x in _NUM.findall(str(text))]
    return None if not n else {"low": min(n[:2]), "high": max(n[:2])}


def to_item(aid: str, d: dict, author: str) -> dict:
    """An Item-shaped dict for `compare_paths`: only answers Michael gave become research entries (an UNKNOWN answer stays missing).
    The provenance id is a deterministic DRY-RUN draft id, not a receipt."""
    research = []
    for key, a in d["answers"].items():
        basis = _ENGINE_BASIS.get(a["basis"])
        if basis is None:
            continue
        if key in ("historical_basis_usd", "minimal_rehab_cash", "themed_rehab_cash"):
            r = _rng(a["value"])
            if r is None:
                continue
            field, val = {"historical_basis_usd": "historical_basis_usd", "minimal_rehab_cash": "minimal:cash", "themed_rehab_cash": "themed:cash"}[key], r
        elif key == "past_tow" or key in _SAFETY_ENGINE:
            field, val = key, a["value"]
        else:
            continue
        pid = "prov_" + hashlib.sha256(f"{aid}|{field}|{a['value']}".encode()).hexdigest()[:24]
        research.append({"field": "owned:" + field, "value": val, "basis": basis, "entered_by": author, "provenance_id": pid})
    return {"item_id": aid, "type": "owned_asset", "owned_asset": True, "title": d.get("title"), "research": research}


def compare(aid: str, d: dict, author: str) -> dict:
    from mbos_economics import owned_asset

    return owned_asset.compare_paths(to_item(aid, d, author), datetime.now(timezone.utc).isoformat())


def _r(v, unit=""):
    if v is None:
        return "<b class=unk>UNKNOWN</b>"
    lo, hi = v["low"], v["high"]
    return f"{unit}{lo:,.0f}" if lo == hi else f"{unit}{lo:,.0f}-{unit}{hi:,.0f}"


def _csrf_pin(csrf, pin_on):
    h = f"<input type='hidden' name='csrf' value='{e(csrf)}'>"
    p = "<label>PIN <input name='pin' type='password' autocomplete='off' required></label>" if pin_on else "<p class='small err'>PIN not configured: changes are refused.</p>"
    return h + p


def render_list(assets: dict, csrf: str, pin_on: bool, flash: str = "") -> str:
    rows = "".join(f"<li><a href='/assets/{e(i)}'>{e(d.get('title'))}</a> <span class='tag inf'>owned</span></li>" for i, d in assets.items())
    spec = intake.load_spec(SPEC)
    return (f"{flash}<div class='card'><h2>My assets (DRY-RUN)</h2><p class='small mut'>Things you already own. Decisions use cash from today; what you "
            f"paid is recorded as sunk history. Your answers are kept as what you said; nothing here can mark anything verified.</p>"
            f"<ul>{rows or '<li class=mut>none yet</li>'}</ul></div>"
            f"<div class='card'><h3>Add an asset</h3><form method='post' action='/assets/add'>{_csrf_pin(csrf, pin_on)}"
            f"<label>Name <input name='title' value='BBQ trailer' required></label>"
            + "".join(f"<p><label>{e(f['ask'])}<br><input name='a_{e(f['key'])}' size='80'></label></p>" for f in spec["fields"] if f["key"] in ("historical_basis_usd", "past_tow"))
            + "<button>Add asset</button></form></div>")


def render_card(aid: str, d: dict, cmp: dict, csrf: str, pin_on: bool, flash: str = "") -> str:
    got = "".join(f"<tr><td>{e(k)}</td><td>{'<b class=unk>UNKNOWN</b>' if a['basis'] == 'UNKNOWN' else e(a['value'])}</td>"
                  f"<td><span class='tag inf'>{e(a['basis'])}</span></td></tr>" for k, a in d["answers"].items())
    rw, rec, sb = cmp["roadworthiness"], cmp["recommendation"], cmp["sunk_basis"]["historical_basis_usd"]
    paths = "".join(
        f"<tr><td><b>{e(p['path'])}</b></td><td>{_r(p['incremental_cash'], '$')}</td><td>{_r(p['operator_hours'])}</td><td>{_r(p['days_to_cash'])}</td>"
        f"<td>{_r(p['personal_use_value'] if p['path'] == 'KEEP' else p['finished_resale_range'], '$')}</td><td>{_r(p['net_incremental'], '$')}</td>"
        f"<td>{e(p['risk']['structural'])}</td><td>{e((p['seasonality'] or {}).get('status', 'n/a'))}</td>"
        f"<td>{e(', '.join(p['unknowns'])) or 'none'}</td></tr>" for p in cmp["paths"])
    pick = (f"System leans {e(rec['path'])} ({e(rec['caveat'])})." if rec["path"] != "UNKNOWN"
            else f"<b class=unk>UNKNOWN</b>: no path has all its inputs yet, so nothing is recommended. Missing: {e(', '.join(rec['missing']))}.")
    qs = intake.missing(d)
    form_rows = "".join(
        f"<tr><td>{'<b>SAFETY</b> ' if q['safety_relevant'] else ''}{e(q['ask'])}</td><td><input name='a_{e(q['key'])}'> "
        f"<select name='b_{e(q['key'])}'><option value='stated'>I said / saw it</option><option value='inferred'>my guess</option><option value='unknown'>I don't know</option></select></td></tr>"
        for q in qs if not q["key"].startswith("photo:"))
    angles = [q["key"][6:] for q in qs if q["key"].startswith("photo:")]
    photos = "".join(f"<li>{e(x['ref'])} <span class='tag inf'>photo ref, unverified</span></li>" for x in d["evidence"] if x.get("kind") == "photo")
    return (f"{flash}<div class='card'><h2>{e(d.get('title'))} <span class='tag inf'>OWNED</span> <span class='tag inf'>DRY-RUN</span></h2>"
            f"<p class='small mut'>Verified facts: 0. Nothing is published, sent or spent. Decision basis: {e(cmp['decision_basis'])}. "
            f"Sunk basis (history only, excluded from net, ROI and ranking): {_r(sb, '$')}.</p>"
            f"<p>Roadworthiness: <b>{e(rw['confidence'])}</b>: {e(rw['why'])}.</p><p>{pick}</p>"
            f"<table><tr><th>Path</th><th>Cash from today</th><th>Your hours</th><th>Days to cash</th><th>Resale / own use</th><th>Net</th><th>Structural risk</th><th>Season</th><th>UNKNOWN inputs</th></tr>{paths}</table></div>"
            f"<div class='card'><h3>What you've told me</h3><table><tr><th>Fact</th><th>Value</th><th>Basis</th></tr>{got or '<tr><td colspan=3 class=mut>nothing yet</td></tr>'}</table></div>"
            f"<div class='card'><h3>Inspection checklist and open questions ({len(qs) - len(angles)})</h3>"
            f"<form method='post' action='/assets/{e(aid)}/answer'>{_csrf_pin(csrf, pin_on)}<table>{form_rows}</table>"
            f"<button>Record answers</button></form></div>"
            f"<div class='card'><h3>Photo references ({len(d['evidence'])})</h3><ul>{photos or '<li class=mut>none</li>'}</ul>"
            f"<p class='small mut'>Still needed: {e(', '.join(angles)) or 'none'}.</p>"
            f"<form method='post' action='/assets/{e(aid)}/answer'>{_csrf_pin(csrf, pin_on)}"
            f"<textarea name='p_photo' rows='3' cols='60' placeholder='one file name or link per line, e.g. rear-axle.jpg'></textarea> <button>Add photo references</button></form></div>")
