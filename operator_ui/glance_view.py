"""F-38: the glanceable top of Today: DONE / WORKING / BLOCKED / OPPORTUNITIES / NEXT.

A pure read model (`build`) plus a renderer (`render`). It adds NO write path and NO data of its own:
* DONE lists only items that have an ACTION_EXECUTED or OUTCOME_RECORDED receipt, and shows that receipt's seq.
* An opportunity's figures come from the stored Item; a figure that cannot be computed says UNKNOWN. Net and $/hour are
  the scorecard's expected values (weighted by chance), shown only when the scorecard holds them.
* Every figure carries one evidence label: CONFIRMED (a recorded outcome with a receipt, real source), SIMULATED (test data
  or a dry-run execution), UNVERIFIED (a stored estimate), SPECULATIVE (net not calculable). Nothing here says "earned"
  without an OUTCOME_RECORDED receipt on a non-test item.
* Approve / Hold / Pass post to the existing /areq/<id>/decide endpoint (YES / HOLD / NO). The PIN rule is the spine's.
"""

from __future__ import annotations

import html
from urllib.parse import urlparse

from .card_view import ec
from .ux import requires_step_up

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731

TOP_N = 3
WORKING_STATES = ("APPROVED", "ACTING", "RESEARCHING")
EARNED_KINDS = ("flip_sold", "service_paid", "service_completed")
CSS = """
.glance{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin:0 0 16px}
.glance .gc{background:var(--card);border:2px solid var(--ink);border-radius:8px;padding:10px 12px}
.glance .gc.wide{grid-column:1/-1}.glance h2{color:var(--ink);margin:0 0 6px}
.glance ul{margin:0;padding-left:18px}.glance li{margin:2px 0}.glance .chk{color:var(--yes);font-weight:700}
.glance .blk{border-color:var(--no)}.glance .blk.amber{border-color:var(--mod)}
.glance .lbl{font-size:11px;font-weight:700;border:1px solid currentColor;border-radius:4px;padding:0 5px;letter-spacing:.04em}
.glance .opp{border-top:1px solid var(--line);padding:8px 0}.glance .opp:first-of-type{border-top:0}
.glance .opp dl{display:grid;grid-template-columns:max-content 1fr;gap:1px 10px;margin:4px 0;font-size:14px}
.glance dt{color:var(--mut)}.glance dd{margin:0}.glance .acts{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end}
.glance .acts form{flex:1 1 150px}.glance .acts button{background:var(--ink);color:var(--bg);padding:6px 10px}
.glance .acts input{margin:2px 0}.glance details summary{cursor:pointer;font-weight:600}
.glance a.go{display:block;text-align:center;font-weight:700;padding:10px;background:var(--ink);color:var(--bg);border-radius:6px;text-decoration:none}
"""


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _money(v):
    return f"${v:,.0f}" if _num(v) is not None else None


def is_test_data(item: dict) -> bool:
    """Listings from the fixture/training sources use reserved `.invalid` hosts (RFC 6761) or an `example.` host."""
    for s in item.get("sources") or []:
        host = (urlparse(str(s.get("url") or "")).hostname or "").lower()
        if host.endswith(".invalid") or host.startswith("example.") or host.endswith(".example"):
            return True
    return False


def _safe_url(u):
    return u if urlparse(str(u or "")).scheme in ("http", "https") else None


def opportunity(item: dict, areq: dict, recorded_verdict=None) -> dict:
    """One opportunity card's fields. UNKNOWN (None) for anything the stored Item does not hold."""
    rec = item.get("recommendation") or {}
    d = ((item.get("scores") or {}).get("scorecard") or {}).get("derived") or {}
    econ = item.get("economics") or {}
    acq, reh, res = econ.get("acquisition") or {}, econ.get("rehab") or {}, econ.get("resale") or {}
    job = econ.get("job") or {}
    loc = (item.get("normalized") or {}).get("location") or {}
    flip = item.get("type") == "flip"
    buy = _num(acq.get("expected_buy_price")) if _num(acq.get("expected_buy_price")) is not None else _num(acq.get("ask_price"))
    all_in = None
    if flip and buy is not None and reh.get("repair_scope_known", True) is not False:
        all_in = buy + sum(_num(x) or 0 for x in (acq.get("buy_fees"), reh.get("parts_cost"), reh.get("materials_cost")))
    sell = _num(res.get("target_sell_price")) if flip else _num(job.get("quoted_revenue"))
    net, pph = _num(d.get("ev_net_profit")), _num(d.get("ev_profit_per_hour"))
    verdict = rec.get("verdict")
    note = None
    if verdict == "YES" and net is None:  # YES only as far as the evidence goes
        verdict, note = "MAYBE", "The system said YES but no expected profit is stored, so this is shown as MAYBE."
    src = next((s for s in item.get("sources") or [] if _safe_url(s.get("url"))), None)
    sim = is_test_data(item)
    label = "SIMULATED" if sim else ("SPECULATIVE" if net is None else "UNVERIFIED")
    why = next(iter((rec.get("rationale") or []) + (((item.get("scores") or {}).get("scorecard") or {}).get("reasons") or [])), None)
    return {
        "areq_id": areq["action_request_id"], "item_id": item["item_id"], "status": areq["status"],
        "title": item["normalized"]["title"], "place": ", ".join(x for x in (loc.get("city"), loc.get("state")) if x) or None,
        "source": src["source"] if src else None, "url": _safe_url(src["url"]) if src else None,
        "verdict": verdict, "verdict_note": note, "buy": buy, "all_in": all_in, "sell": sell,
        "sell_label": "Resale" if flip else "Service quote", "net": net, "pph": pph if net is not None else None,
        "confidence": rec.get("confidence", d.get("confidence")), "label": label,
        "missing": rec.get("cheapest_decisive_evidence") or ((item.get("scores") or {}).get("scorecard") or {}).get("cheapest_decisive_evidence"),
        "action": (areq.get("payload") or {}).get("summary") or next(
            (pa["summary"] for pa in rec.get("proposed_actions", []) if pa["capability"] == areq["capability"]), areq["capability"]),
        "why": why, "payload_hash": areq["payload_hash"], "step_up": requires_step_up(areq),
        "hash_ok": None,
    }


def build(store, now, parked=(), state="") -> dict:
    """The five cards' content from live rows. `parked` is [(item, gap text)] as the queue computes it."""
    from .views import payload_hash_verified

    areqs = store.action_requests()
    opens, done, working = [], [], []
    items: dict = {}

    def item_of(a):
        if a["item_id"] not in items:
            items[a["item_id"]] = store.item(a["item_id"])
        return items[a["item_id"]]

    for a in areqs:
        if a["status"] in ("pending_approval", "held"):
            o = opportunity(item_of(a), a)
            o["hash_ok"] = payload_hash_verified(a)
            opens.append(o)
    opens.sort(key=lambda o: (o["net"] is None, -(o["net"] or 0)))
    seen = set()
    for a in areqs:
        if a["item_id"] in seen or a["status"] in ("pending_approval", "held"):
            continue
        rs = [r for r in store.receipts(item_id=a["item_id"]) if r["type"] in ("ACTION_EXECUTED", "OUTCOME_RECORDED")]
        if not rs:
            continue
        seen.add(a["item_id"])
        it = item_of(a)
        out = rs[-1]
        outcomes = [x for x in store.outcomes(a["item_id"]) if x.get("kind") in EARNED_KINDS and _num((x.get("realized") or {}).get("net_profit")) is not None]
        has_outcome = any(r["type"] == "OUTCOME_RECORDED" for r in rs)
        net = _num(outcomes[-1]["realized"]["net_profit"]) if outcomes and has_outcome else None
        dry = any((r.get("effector_response") or {}).get("dry_run") is True for r in rs)
        label = "CONFIRMED" if (net is not None and not is_test_data(it)) else ("SIMULATED" if (dry or is_test_data(it)) else "UNVERIFIED")
        done.append({"item_id": a["item_id"], "title": it["normalized"]["title"], "seq": out["seq"], "receipt_type": out["type"],
                     "net": net, "label": label, "dry_run": dry and net is None})
    for st in WORKING_STATES:
        for it in store.items_in_states((st,)):
            if st == "RESEARCHING":
                continue  # a parked item belongs to BLOCKED (it waits on Michael), not to a running job
            working.append({"item_id": it["item_id"], "title": it["normalized"]["title"], "state": st})
    awaiting = [d for d in done if d["receipt_type"] == "ACTION_EXECUTED"]
    blocked = []
    if str(state).startswith("FROZEN"):
        blocked.append({"what": "System is FROZEN: nothing will be carried out.", "action": "Release it on the server: mbos panic off --reason \"...\"", "red": True})
    if getattr(state, "owner_login_missing", False):
        blocked.append({"what": "Owner writes will be refused (worker login).", "action": "Set MBOS_OWNER_DATABASE_URL and restart the UI.", "red": True})
    for it, gap in parked:
        blocked.append({"what": it["normalized"]["title"], "action": gap, "item_id": it["item_id"], "red": False})
    nxt = None
    if opens:
        o = opens[0]
        nxt = {"text": f"Decide: {o['title']}", "href": f"/item/{o['item_id']}"}
    elif awaiting:
        nxt = {"text": f"Record what happened: {awaiting[0]['title']}", "href": f"/item/{awaiting[0]['item_id']}"}
    elif parked:
        nxt = {"text": f"Give the system what it needs: {parked[0][0]['normalized']['title']}", "href": f"/item/{parked[0][0]['item_id']}"}
    return {"done": done, "working": working, "blocked": blocked, "opportunities": opens, "next": nxt}


def _form(o, csrf, decision, inner, btn):
    return (f'<form method="post" action="/areq/{e(o["areq_id"])}/decide"><input type="hidden" name="csrf" value="{e(csrf)}">'
            f'<input type="hidden" name="return" value="item"><input type="hidden" name="payload_hash_seen" value="{e(o["payload_hash"])}">'
            f'<input type="hidden" name="decision" value="{decision}">{inner}<button>{btn}</button></form>')


def _opp(o, csrf):
    def row(k, v, extra=""):
        return f"<dt>{k}</dt><dd>{v if v is not None else '<b class=unk>UNKNOWN</b>'}{extra}</dd>"
    place = e(o["place"]) if o["place"] else None
    src = (f'<a href="{e(o["url"])}" rel="noreferrer noopener">{e(o["source"])}</a>' if o["url"] else (e(o["source"]) if o["source"] else None))
    held = " · <b>on HOLD</b>" if o["status"] == "held" else ""
    cost = _money(o["all_in"])
    pin = ('<input name="pin" type="password" autocomplete="off" placeholder="PIN" aria-label="Step-up PIN" required>' if o["step_up"] else "")
    approve = (_form(o, csrf, "YES", pin, "Approve") if o["hash_ok"] else
               '<span class="small bad">Approve unavailable: payload hash does not verify. Open More details.</span>')
    acts = (approve + _form(o, csrf, "HOLD", '<input type="hidden" name="hold_preset" value="24h">'
                            '<input name="reason" maxlength="500" placeholder="Why hold (optional)" aria-label="Hold reason">', "Hold")
            + _form(o, csrf, "NO", '<input name="reason" maxlength="500" placeholder="Why pass (required)" aria-label="Pass reason" required>', "Pass"))
    return (f'<div class="opp"><div class="row"><b>{ec(o["title"])}</b> <span class="badge v-{e(o["verdict"])}">{e(o["verdict"] or "NO VERDICT")}</span>'
            f' <span class="lbl" title="evidence label">{e(o["label"])}</span>{held}</div>'
            f'<div class="small mut">{place or "location UNKNOWN"} · {src or "source link UNKNOWN"}</div>'
            f'<dl>{row("Buy", _money(o["buy"]))}{row("All-in cost", cost)}{row(o["sell_label"], _money(o["sell"]))}'
            f'{row("Expected net", _money(o["net"]), " <span class=small>weighted by chance, not a promise</span>" if o["net"] is not None else "")}'
            f'{row("$/hour", _money(o["pph"]))}{row("Confidence", e(o["confidence"]) if o["confidence"] is not None else None)}'
            f'{row("Still unverified", ec(o["missing"]) if o["missing"] else "nothing stated")}'
            f'{row("Next action", ec(o["action"]))}</dl>'
            + (f'<p class="small">{ec(o["why"])}</p>' if o["why"] else "") + (f'<p class="small unk">{e(o["verdict_note"])}</p>' if o["verdict_note"] else "")
            + f'<div class="acts">{acts}<a href="/item/{e(o["item_id"])}">More details</a></div></div>')


def render(m, csrf) -> str:
    done = "".join(
        f'<li><span class="chk" title="receipt-verified">&#10003;</span> <a href="/item/{e(d["item_id"])}">{ec(d["title"])}</a> '
        f'<span class="small mut">receipt #{e(d["seq"])} · {e(d["receipt_type"])}</span> <span class="lbl">{e(d["label"])}</span>'
        f'{" <span class=small>dry-run: nothing real happened</span>" if d["dry_run"] else ""}'
        f'{" <span class=small>net " + _money(d["net"]) + "</span>" if d["net"] is not None and d["label"] == "CONFIRMED" else ""}</li>'
        for d in m["done"][:TOP_N])
    more_done = "".join(f'<li><span class="chk">&#10003;</span> {ec(d["title"])} <span class="small mut">receipt #{e(d["seq"])}</span> <span class="lbl">{e(d["label"])}</span></li>' for d in m["done"][TOP_N:])
    work = "".join(f'<li><a href="/item/{e(w["item_id"])}">{ec(w["title"])}</a> <span class="small mut">{e(w["state"])}</span></li>' for w in m["working"])
    blk = ""
    for b in m["blocked"]:
        link = f' <a href="/item/{e(b["item_id"])}">open</a>' if b.get("item_id") else ""
        blk += (f'<div class="gc blk{"" if b["red"] else " amber"}"><h2>Blocked</h2><b>{ec(b["what"])}</b>'
                f'<div class="small">Your action: {ec(b["action"])}{link}</div></div>')
    if not blk:
        blk = '<div class="gc"><h2>Blocked</h2><p class="mut">Nothing is blocked.</p></div>'
    opps = m["opportunities"]
    top = "".join(_opp(o, csrf) for o in opps[:TOP_N]) or '<p class="mut">No open opportunity needs a decision.</p>'
    rest = (f'<details><summary>{len(opps) - TOP_N} more</summary>{"".join(_opp(o, csrf) for o in opps[TOP_N:])}</details>'
            if len(opps) > TOP_N else "")
    nxt = (f'<a class="go" href="{e(m["next"]["href"])}">{ec(m["next"]["text"])}</a>' if m["next"]
           else '<p class="mut">Nothing to do right now.</p>')
    return (f"<style>{CSS}</style><section class='glance' aria-label='At a glance'>"
            f'<div class="gc"><h2>Done</h2>' + (f"<ul>{done}</ul>" if done else '<p class="mut">Nothing receipt-verified yet.</p>')
            + (f"<details><summary>{len(m['done']) - TOP_N} more</summary><ul>{more_done}</ul></details>" if more_done else "") + "</div>"
            f'<div class="gc"><h2>Working</h2>' + (f"<ul>{work}</ul>" if work else '<p class="mut">No job is running.</p>') + "</div>"
            f"{blk}"
            f'<div class="gc"><h2>Next</h2>{nxt}</div>'
            f'<div class="gc wide"><h2>Opportunities</h2>{top}{rest}</div></section>')
