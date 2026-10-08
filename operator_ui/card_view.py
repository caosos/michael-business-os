"""F-13: Michael's opportunity card (ADR-0011) as the primary Operator UI view, at /item/<id>.

The page is a pure rendering of `mbos.card.build_card(...)`; this module adds NO data of its own.
* UNKNOWN stays UNKNOWN, visibly, with the card's reason. Nothing is filled in, guessed or defaulted.
* Every card string is untrusted listing/seller/lane text and is HTML-escaped.
* The card's own `validate_card` result is shown; a failing card is flagged, never silently rendered.
* The YES/NO/MODIFY/HOLD controls (human channel only, R14) sit beneath the RECOMMENDATION block and are
  the same forms and checks as the technical request page (`server.render_decide`).
"""

from __future__ import annotations

import html
from typing import Any

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731


def ec(v, limit: int = 300) -> str:
    """Escape UNTRUSTED display text after `mbos.card.clean_text` (strips control, ANSI and bidi characters, caps length).
    Only for text that is displayed, never for data that is edited and re-submitted."""
    from mbos.card import clean_text

    return html.escape(clean_text("" if v is None else v, limit))

_BASIS_CLASS = {"FACT": "fact", "INFERENCE": "inf", "RECOMMENDATION": "rec"}


def unknown(d: Any) -> bool:
    return isinstance(d, dict) and d.get("value") == "UNKNOWN"


def datum(d: dict, money: bool = False, unit: str = "") -> str:
    """One card datum. UNKNOWN is rendered as UNKNOWN with its reason; known values show their basis and provenance."""
    if unknown(d):
        why = f" <span class='small mut'>({e(d['reason'])})</span>" if d.get("reason") else ""
        return f"<b class='unk'>UNKNOWN</b>{why}"
    v = d["value"]
    if d.get("low") is not None and d.get("high") is not None:
        txt = f"${d['low']:,.0f}–${d['high']:,.0f}" if money else f"{d['low']}–{d['high']}"
    elif money and isinstance(v, (int, float)) and not isinstance(v, bool):
        txt = f"${v:,.0f}"
    elif isinstance(v, (list, dict)):
        txt = ", ".join(map(str, v)) if isinstance(v, list) else str(v)
    elif isinstance(v, bool):
        txt = "yes" if v else "no"
    else:
        txt = str(v)
    u = f" {d['unit']}" if d.get("unit") and not money else ""
    basis = d.get("basis", "")
    prov = (f" <a class='small' href='/provenance/{e(d['provenance_id'])}'>provenance</a>" if d.get("provenance_id") else "")
    note = f" <span class='small mut'>{e(d['note'])}</span>" if d.get("note") else ""
    return f"{e(txt)}{e(u)} <span class='tag {_BASIS_CLASS.get(basis, '')}'>{e(basis)}</span>{prov}{note}"


def _row(label: str, d: dict, money: bool = False) -> str:
    return f"<tr><td>{e(label)}</td><td>{datum(d, money)}</td></tr>"


def _link_prov(pid: str) -> str:
    return f"<a href='/provenance/{e(pid)}'><code>{e(pid)}</code></a>"


def render_header(card: dict) -> str:
    i = card["item"]
    link = f"<a href='{e(i['url'])}' rel='noreferrer noopener'>listing</a>" if str(i.get("url", "")).startswith(("http://", "https://")) else e(i.get("url"))
    return (f"<div class='card'><div class='row'><span class='badge {e(i['type'])}'>{'FLIP' if i['type'] == 'flip' else 'SERVICE'}</span>"
            f"<span class='mut'>{e(i['category'])}</span><span class='grow'></span>"
            f"<span class='small mut'>{e(i['source'])} · {link} · card <code>{e(card['card_hash'][:19])}</code></span></div>"
            f"<h1>{ec(i['title'])}</h1>"
            f"<div>{datum(i['location'])} · {datum(i['distance_miles'])} · asking {datum(i['asking_price'], True)}</div>"
            f"<div class='small'>make/model: {datum(i['make_model'])}</div></div>")


def render_listing_activity(card: dict) -> str:
    la = card["listing_activity"]
    rec = "".join(f"<li>{e(x)}</li>" for x in la["recent_activity"])
    return ("<div class='card'><h2>Listing activity</h2><table>" + _row("Posted", la["posted_at"]) + _row("Last updated", la["updated_at"])
            + _row("Age (days)", la["age_days"]) + _row("Suspected relist", la["suspected_relist"]) + _row("Stale risk", la["stale_risk"])
            + f"</table>{'<ul>' + rec + '</ul>' if rec else ''}</div>")


def render_seller(card: dict) -> str:
    s = card["seller"]
    rows = "".join(_row(k.replace("_", " ").capitalize(), s[k]) for k in
                   ("account_age", "rating", "prior_listings", "complaint_signals", "response_history", "inconsistencies"))
    conf = s["confidence"]
    allunk = all(unknown(s[k]) for k in ("account_age", "rating", "prior_listings", "complaint_signals", "response_history", "inconsistencies"))
    head = ("<p class='unk'><b>Seller style: UNKNOWN.</b> This source does not expose seller history, and the system will not guess.</p>"
            if allunk else "")
    return (f"<div class='card'><h2>Seller</h2>{head}<table>{rows}</table>"
            f"<p class='small'>Confidence: {'<b class=unk>UNKNOWN</b>' if conf == 'UNKNOWN' else e(conf)}</p></div>")


def render_why(card: dict) -> str:
    wp = card.get("why_provenance") or []
    src = (" <span class='small'>Lane-supplied reasons come from: " + " ".join(_link_prov(p) for p in wp) + "</span>") if wp else ""
    return f"<div class='card'><h2>Why it is interesting</h2><ul>{''.join(f'<li>{e(w)}</li>' for w in card['why'])}</ul>{src}</div>"


def render_flags(card: dict) -> str:
    """item.flags are listing-level warnings from lane B (injection_suspected, needs_review, ...): never hidden."""
    flags = card["item"].get("flags") or []
    if not flags:
        return ""
    strong = [f for f in flags if f in ("injection_suspected", "needs_review")]
    return ("<div class='flash err'><b>WARNING: this listing was flagged.</b> "
            + ("Its text needs your eyes before you act: do not trust it." if strong else "Read the listing yourself.")
            + "<ul>" + "".join(f"<li><code>{ec(f, 80)}</code></li>" for f in flags) + "</ul></div>")


def render_economics(card: dict) -> str:
    x = card["economics"]
    lines = [("Asking price", "asking_price"), ("Recommended opening offer", "recommended_opening_offer"),
             ("Maximum acquisition price", "maximum_acquisition_price"), ("Repair / material cost", "expected_repair_material_cost"),
             ("Transport cost", "transport_cost"), ("Total cash at risk", "total_cash_at_risk"),
             ("Resale, conservative", "resale_conservative"), ("Resale, likely", "resale_likely"),
             ("Resale, optimistic", "resale_optimistic"), ("Expected gross profit", "expected_gross_profit"),
             ("Expected net profit", "expected_net_profit"), ("Expected profit per hour", "expected_profit_per_hour")]
    rows = "".join(_row(label, x[k], True) for label, k in lines) + _row("Expected days to cash", x["expected_days_to_cash"])
    return f"<div class='card'><h2>Estimated numbers</h2><table>{rows}</table></div>"


def render_value_add(card: dict) -> str:
    v = card["value_add_plan"]
    risks = "".join(
        f"<li><b>{e(r['risk'])}</b> <span class='tag {_BASIS_CLASS.get(r['basis'], '')}'>{e(r['basis'])}</span>"
        f"{' · source: ' + e(r['source']) if r.get('source') else ''}"
        f"{' ' + _link_prov(r['provenance_id']) if r.get('provenance_id') else ''}</li>" for r in v["model_specific_risks"])
    return (f"<div class='card'><h2>Value-add plan</h2><p>{datum(v['plan'])}</p>"
            + (f"<h2 style='margin-top:10px'>Model-specific risks</h2><ul>{risks}</ul>" if risks else
               "<p class='small mut'>No sourced model-specific risks on the card.</p>") + "</div>")


def render_seasonality(card: dict) -> str:
    se = card["seasonality"]
    months = f"<tr><td>Peak months</td><td>{e(', '.join(map(str, se['peak_months'])))}</td></tr>" if se.get("peak_months") else ""
    return ("<div class='card'><h2>Seasonality</h2><table>" + _row("Note", se["note"]) + _row("Demand now", se["demand_now"])
            + _row("Likely to hold", se["hold_likely"]) + months + "</table></div>")


def render_transport(card: dict) -> str:
    lg = card["logistics"]
    mode = lg["transport_mode"]
    verdict = {"fits_truck": "Fits the truck. No trailer required.",
               "requires_trailer": "Requires a trailer (not owned). A borrowed trailer must be confirmed with the lender before pickup."}.get(
        mode.get("value"), "UNKNOWN (not yet classified)") if not unknown(mode) else "UNKNOWN (not yet classified)"
    rows = "".join(_row(label, lg[k], money) for label, k, money in [
        ("Transport mode", "transport_mode", False), ("Trailer needed", "trailer_needed", False), ("Trailer owned", "trailer_owned", False),
        ("Borrowed trailer possible", "borrowed_trailer_possible", False), ("Borrowed trailer confirmed", "borrowed_trailer_confirmed", False),
        ("Round-trip miles", "trip_miles_round_trip", False), ("Trip hours", "trip_hours", False), ("Fuel cost", "fuel_cost", True),
        ("Difficulty", "difficulty", False)])
    return f"<div class='card'><h2>Transport</h2><p><b>{e(verdict)}</b></p><table>{rows}</table></div>"


def render_status(card: dict) -> str:
    st = card["status"]
    rows = "".join(
        f"<tr><td>{e(t['at'])}</td><td><b>{e(t['stage'])}</b>"
        f"{' <span class=\"tag rec\">DRY-RUN: simulated, nothing sent</span>' if t.get('dry_run') else ''}</td>"
        f"<td><code>{e(t['receipt_id'])}</code></td></tr>" for t in st["timeline"])
    note = "<p class='small mut'>Stages without an event source (NEGOTIATING, QUALIFIED) are shown only when they happen. They are never invented.</p>"
    return (f"<div class='card'><h2>System status</h2><p>Now: <b>{e(st['current'])}</b></p>"
            f"<table><tr><th>When</th><th>Stage</th><th>Proved by receipt</th></tr>{rows}</table>{note}</div>")


def render_recommendation(card: dict) -> str:
    r = card["recommendation"]
    wait = " / WAIT FOR RESPONSE" if r["waiting"] else ""
    step = ("<span class='badge v-MAYBE'>needs step-up approval (PIN)</span>" if r.get("requires_step_up") else "")
    return (f"<div class='card rec'><h2>Recommendation</h2><p style='font-size:22px;margin:4px 0'><b>{e(r['action'])}{e(wait)}</b> {step}</p>"
            f"<p>{e(r['why'])}</p></div>")


def render_trail(card: dict) -> str:
    rows = []
    for t in card["activity_trail"]:
        ins = " ".join(_link_prov(p) for p in t["inputs"])
        rows.append(f"<tr><td>{e(t['at'])}</td><td>{e(t['agent'])}</td><td>{e(t['what'])}</td><td>{e(t['why'])}</td><td>{ins}</td>"
                    f"<td>{e(t['result'])}</td><td><code>{e(t['receipt_id'])}</code></td><td>{e(t['next_action'])}</td></tr>")
    return ("<div class='card'><h2>Activity trail (every action has a receipt)</h2>"
            "<div style='overflow-x:auto'><table><tr><th>When</th><th>Agent</th><th>What</th><th>Why</th><th>Inputs (provenance)</th>"
            f"<th>Result</th><th>Receipt</th><th>Next action</th></tr>{''.join(rows)}</table></div></div>")


def render_unknowns(card: dict) -> str:
    u = card["unknowns"]
    body = ("<ul>" + "".join(f"<li><code>{e(x)}</code></li>" for x in u) + "</ul>") if u else "<p class='mut'>Nothing unknown.</p>"
    return f"<div class='card'><h2>UNKNOWN ({len(u)}): what the system could not establish</h2>{body}</div>"


def needs_model_knowledge(card: dict) -> bool:
    """True when the card shows no lane-SOURCED model knowledge (FACT/INFERENCE). Michael's own notes are
    RECOMMENDATION and do not count as sourced, so the prompt stays until a sourced recall exists."""
    return not any(r.get("basis") in ("FACT", "INFERENCE") for r in card["value_add_plan"]["model_specific_risks"])


def render_note_section(card: dict, csrf: str, lane_d: bool, categories: list[str], kinds: list[str], basis_choices: list[str],
                        flash_reasons: list[str] | None = None, values: dict | None = None) -> str:
    """\"Add what you know about this model\" (F-14). The author is NOT a form field: the server sets it."""
    v = values or {}
    i = card["item"]
    cat = v.get("category") or (i["category"] if i["category"] in categories else "")
    prompt = needs_model_knowledge(card)
    head = ("Add what you know about this model" if prompt else "Add another note about this model")
    why = ("<p class='unk'><b>No sourced model knowledge is on this card.</b> Your own experience is the most valuable thing you can add here; "
           "it shows on this and later cards as <b>your recommendation</b> (never as a fact), behind any sourced recall.</p>"
           if prompt else "<p class='small mut'>Your notes show on cards as RECOMMENDATION, behind sourced recalls.</p>")
    if i["type"] != "flip":
        return (f"<div class='card'><h2>{e(head)}</h2><p class='small mut'>Model notes cover flip equipment categories in this version; "
                f"this is a {e(i['type'])}.</p></div>")
    errs = ("<div class='flash err'><b>Note not saved.</b><ul>" + "".join(f"<li>{e(r)}</li>" for r in (flash_reasons or [])) + "</ul></div>"
            if flash_reasons else "")
    if not lane_d:
        return (f"<div class='card'><h2>{e(head)}</h2>{why}{errs}<p class='bad'>Notes need the lane D store "
                "(<code>MBOS_STATE_BACKEND=lane_d</code>); this UI is running on the reference backend.</p></div>")
    opts = lambda xs, sel: "".join(f"<option value='{e(x)}'{' selected' if x == sel else ''}>{e(x)}</option>" for x in xs)  # noqa: E731
    mm = card["item"]["make_model"]
    hint = f"Card make/model: {datum(mm)}" if not unknown(mm) else "Card make/model: <b class='unk'>UNKNOWN</b>, so please type the make and model."
    return f"""<div class="card" id="note"><h2>{e(head)}</h2>{why}{errs}
<form method="post" action="/item/{e(card['item_id'])}/note"><input type="hidden" name="csrf" value="{e(csrf)}">
<p class="small">{hint}. A note must name a make <b>and</b> a model. Several are allowed, separated by commas. Entered as <b>you</b> (author is set by the system and needs your PIN).</p>
<div class="decide"><label>Category<select name="category">{opts(categories, cat)}</select></label>
<label>Make(s)<input name="makes" value="{e(v.get('makes'))}" maxlength="200" required></label>
<label>Model(s)<input name="models" value="{e(v.get('models'))}" maxlength="200" required></label>
<label>Kind of knowledge<select name="kind">{opts(kinds, v.get('kind'))}</select></label></div>
<label>What is specific to THIS model (max 600 characters; no generic advice)<textarea name="statement" maxlength="600" required>{e(v.get('statement'))}</textarea></label>
<label>Plan hint (optional)<input name="plan_hint" maxlength="600" value="{e(v.get('plan_hint'))}"></label>
<div class="decide"><label>How do you know?<select name="basis_of_knowledge">{opts(basis_choices, v.get('basis_of_knowledge'))}</select></label>
<label>Detail (optional)<input name="basis_detail" maxlength="200" value="{e(v.get('basis_detail'))}"></label>
<label>Reference link (optional, https)<input name="reference_url" maxlength="500" value="{e(v.get('reference_url'))}"></label>
<label>Step-up PIN<input name="pin" type="password" autocomplete="off" required></label></div>
<p class="small mut">This is stored as your recommendation, append-only and receipted. Edits are new notes; nothing is overwritten.</p>
<button class="b-HOLD" style="width:auto">Save my note</button></form>
<p class="small"><a href="/notes">All my notes</a></p></div>"""


def render_followup_section(card: dict, item_state: str, csrf: str, lane_d: bool, has_open_request: bool,
                            flash_reasons: list[str] | None = None, values: dict | None = None) -> str:
    """F-11: Follow-up / Offer / Quote. Each button PROPOSES a separate request; nothing is sent until Michael's own
    YES (binding drafts need the PIN)."""
    v = values or {}
    errs = ("<div class='flash err'><b>Not created.</b><ul>" + "".join(f"<li>{e(r)}</li>" for r in (flash_reasons or [])) + "</ul></div>"
            if flash_reasons else "")
    if has_open_request:  # a request is already waiting on Michael: decide it first (but never hide a refusal)
        return f"<div class='card'><h2>Next step</h2>{errs}</div>" if errs else ""
    if item_state != "ACTED":
        return ("<div class='card'><h2>Next step</h2><p class='small mut'>Follow-ups open once the first action has been carried out "
                f"(the item is now {e(item_state)}).</p></div>")
    if not lane_d:
        return f"<div class='card'><h2>Next step</h2>{errs}<p class='bad'>Follow-ups need the lane D store.</p></div>"
    i = card["item"]
    flip = i["type"] == "flip"
    binding = (f"""<form method="post" action="/item/{e(card['item_id'])}/followup"><input type="hidden" name="csrf" value="{e(csrf)}">
<input type="hidden" name="kind" value="offer"><h2 style="margin-top:10px">Draft an offer (BINDING)</h2>
<div class="decide"><label>Cash offer $<input name="amount" inputmode="decimal" value="{e(v.get('amount'))}" required></label>
<label>Pickup window<input name="pickup_window" value="{e(v.get('pickup_window'))}" maxlength="40"></label>
<label>Offer open until<input name="expires" value="{e(v.get('expires'))}" maxlength="40"></label></div>
<p class="small mut">Never above the asking price. Creates its own request that needs your YES and PIN.</p>
<button class="b-MODIFY" style="width:auto">Draft offer</button></form>""" if flip else
               f"""<form method="post" action="/item/{e(card['item_id'])}/followup"><input type="hidden" name="csrf" value="{e(csrf)}">
<input type="hidden" name="kind" value="quote"><h2 style="margin-top:10px">Draft a quote (BINDING)</h2>
<div class="decide"><label>Quote $<input name="amount" inputmode="decimal" value="{e(v.get('amount'))}" required></label>
<label>Scope<input name="scope" value="{e(v.get('scope'))}" maxlength="120"></label>
<label>Deposit %<input name="deposit_pct" value="{e(v.get('deposit_pct') or '25')}" maxlength="2"></label>
<label>Quote valid until<input name="expires" value="{e(v.get('expires'))}" maxlength="40"></label></div>
<p class="small mut">Creates its own request that needs your YES and PIN.</p>
<button class="b-MODIFY" style="width:auto">Draft quote</button></form>""")
    return f"""<div class="card" id="next"><h2>Next step</h2>{errs}
<p class="small mut">Each button drafts a <b>separate</b> request for your approval. Nothing is sent until you say YES.</p>
<form method="post" action="/item/{e(card['item_id'])}/followup"><input type="hidden" name="csrf" value="{e(csrf)}">
<input type="hidden" name="kind" value="followup"><button class="b-HOLD" style="width:auto">Draft follow-up questions</button></form>
{binding}</div>"""


def render_item_card(card: dict, errors: list[str], controls_html: str, hold_html: str = "") -> str:
    """Whole page body. `controls_html` is server.render_decide(...) for the open request ('' when none)."""
    banner = ""
    if errors:
        banner = ("<div class='flash err'><b>This card failed its own validation.</b> Treat it with suspicion and report it:<ul>"
                  + "".join(f"<li>{e(x)}</li>" for x in errors[:8]) + "</ul></div>")
    decide = (f"<div class='card'><h2>Your decision</h2>{hold_html}{controls_html}</div>" if controls_html else
              "<div class='card'><h2>Your decision</h2><p class='mut'>No open request is waiting for a decision on this item.</p></div>")
    return (banner + render_flags(card) + render_header(card)
            + "<div class='grid'>" + render_listing_activity(card) + render_seller(card) + "</div>"
            + render_why(card) + render_economics(card)
            + "<div class='grid'>" + render_value_add(card) + render_seasonality(card) + render_transport(card) + "</div>"
            + render_status(card) + render_recommendation(card) + decide + render_trail(card) + render_unknowns(card))
