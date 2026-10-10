"""F-39: asset-deal decisions and the resale workflow, on the C-32/C-33 economics (`mbos_economics.asset_deal`).

* `decide` runs the engine for one auction lot / listing and returns the card fields: BUY / WATCH / PASS. BUY is only ever a
  recommendation that needs Michael's own approval; nothing here bids, buys, contacts a seller or publishes (DRY-RUN).
* `Book` is the in-memory resale ledger: an item moves intake -> photos -> listing -> listed -> sold. Every step and the sale write
  a receipt. Realized profit is "earned" only for a sale Michael marks as real; a simulated/demo sale is always labelled
  SIMULATED and is never counted as earned.
* `render_hunt` is Michael's Morning Money Hunt shape: bottom line, small ranked table, one block per item, what changed,
  what was rejected, today's best move. Anything the inputs do not hold is UNKNOWN.
"""

from __future__ import annotations

import html
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from mbos_economics import asset_deal

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
STAGES = ("intake", "photos", "listing", "listed", "sold")
PRINCIPAL = 500.0  # the owner's protected bankroll (DEAL_SNIFFER_START_HERE 1)
MAX_TEXT, MAX_MONEY = 500, 1_000_000
ACTION_NOTE = {"BUY": "BUY needs your approval; the system never bids or buys", "WATCH": "WATCH: not a buy yet", "PASS": "PASS: do not spend"}

DEMO_DEALS = {  # DEMO fixture, never a live listing (hosts reserved). Owner target 1500 vs system estimate: both shown.
    "demo-splitter": {"item_id": "demo-splitter", "title": "DEMO CountyLine 32-ton log splitter, no engine", "source": "DEMO fixture (no live link)",
                      "location": "Conway, AR (DEMO)", "distance_mi": 25, "asset_class": "component_machine", "hammer_price": 450,
                      "buyer_premium_pct": 0.10, "sales_tax_rate": 0.065, "pickup_cost": 20, "transport_cost": 40, "labor_hours": 4,
                      "days_to_sell": 14, "pickup_wait_hours": 48, "current_bid": 450, "bid_count": 24, "hours_left": 6,
                      "owner_resale_target": {"value": 1500, "source": "Michael", "note": "DEMO owner target"},
                      "repair": {"skills_cover_repair": True, "parts_cost": 60, "michael_hours": 3, "repair_days": 2},
                      "comps": [{"asking_price": 1800}], "demand": "UNKNOWN", "demo": True,
                      "url": "https://listings.example.invalid/lot/splitter-32t", "condition": "no engine, hydraulics unknown", "category": "component_machine",
                      "sale_type": "auction", "title_status": "no title", "weight_lb": 900, "length_ft": 8,
                      "description": "DEMO ad text.\nNo engine. Sold as is.\nCall <b>Bob</b> after 5.\nPickup only.\nCash.\nNo returns.\nHydraulics not tested.",
                      "photos": [{"url": "https://img.example.invalid/splitter-1.jpg", "source": "DEMO fixture", "captured_at": "2026-10-09"},
                                 {"url": "https://img.example.invalid/mock.jpg", "kind": "mockup", "source": "DEMO mockup"}]},
               "demo-utility-trailer": {"item_id": "demo-utility-trailer", "title": "DEMO 14 ft tandem-axle utility trailer", "source": "DEMO fixture (no live link)",
                      "location": "Little Rock, AR (DEMO)", "distance_mi": 32, "asset_class": "towable", "paperwork": {"class": "titled"}, "hammer_price": 1400, "buyer_premium_pct": 0,
                      "sales_tax_rate": 0.065, "pickup_cost": 0, "transport_cost": 0, "labor_hours": 2, "days_to_sell": 10, "pickup_wait_hours": 24,
                      "comps": [{"sold_price": 2100}, {"sold_price": 2300}, {"sold_price": 2200}, {"asking_price": 2600}], "demand": "UNKNOWN", "demo": True,
                      "url": "https://listings.example.invalid/ad/utility-14", "condition": "good, new tires", "category": "towable", "trailer_subtype": "utility",
                      "sale_type": "fixed", "title_status": "clean title", "weight_lb": 2800, "length_ft": 14,
                      "description": "DEMO ad: 14' tandem axle, new tires, clean title.", "photos": []}}


UI_KEYS = ("title", "source", "location", "distance_mi", "demo", "demand", "url", "photos", "description", "condition", "category", "trailer_subtype",
           "title_status", "sale_type", "weight_lb", "length_ft", "transport_required")  # shown on the card, never fed to the engine


def _d(v):
    return float(v) if v is not None else None


def money(v) -> str:
    return "UNKNOWN" if v is None else f"${float(v):,.2f}"


def decide(deal: dict) -> dict:
    """Card fields from the economics engine. Never raises on a bad lot: an uncomputable lot is WATCH with UNKNOWNs named."""
    inp = {k: v for k, v in deal.items() if k not in UI_KEYS}
    try:
        r = asset_deal.evaluate(inp)
    except Exception as ex:  # noqa: BLE001 - one bad lot must not break the page
        r = {"computable": False, "unknowns": [f"engine error {type(ex).__name__}"], "reasons": []}
    comp = r.get("computable")
    verdict = r.get("verdict")
    action = "PASS" if verdict == "PASS" else "BUY" if verdict == "YES" else "WATCH"
    mb = (r.get("suggested_max_bid") or {})
    fc = r.get("bid_forecast") or {}
    cost = r.get("cost") or {}
    ev = r.get("evidence") or {}
    conf = "UNKNOWN" if not comp else ("HIGH" if ev.get("sold_comps_used", 0) >= 3 and not (r.get("resale") or {}).get("owner_target") else
                                       "MEDIUM" if ev.get("sold_comps_used", 0) else "LOW (owner target / estimate, not sold comps)")
    return {"id": deal.get("item_id"), "title": deal.get("title") or deal.get("item_id"), "demo": bool(deal.get("demo")), "action": action,
            "note": ACTION_NOTE[action], "computable": bool(comp), "unknowns": r.get("unknowns") or [], "reasons": r.get("reasons") or [],
            "source": deal.get("source") or "UNKNOWN", "location": deal.get("location") or "UNKNOWN", "distance": deal.get("distance_mi"),
            "bid": deal.get("current_bid", deal.get("hammer_price")), "bids": deal.get("bid_count"), "hours_left": deal.get("hours_left"),
            "all_in": cost.get("all_in"), "transport": cost.get("pickup_and_transport"), "repair": (r.get("extras") or {}).get("repair_cost"),
            "paperwork": ((r.get("paperwork") or {}).get("class") or "n/a (no paperwork class given)"), "resale": r.get("resale") or {},
            "net": (r.get("net") or {}).get("expected"), "days": r.get("days_to_cash"), "ppd": r.get("profit_per_day"),
            "pph": r.get("profit_per_labor_hour"), "tied_up": r.get("capital_tied_up"), "at_risk": r.get("capital_at_risk"),
            "max_bid": mb.get("max_bid"), "max_bid_binding": mb.get("binding"), "forecast": fc, "confidence": conf,
            "demand": deal.get("demand") or "UNKNOWN", "sold_comps": ev.get("sold_comps_count", 0), "asking_comps": ev.get("asking_comps_count", 0),
            "flags": r.get("flags") or {}, "verdict": verdict, "deal": deal}


def _row(label, val):
    return f"<dt>{e(label)}</dt><dd>{e(val)}</dd>"


def proof_html(c: dict, realized: dict | None = None) -> str:
    """The evidence behind a deal: every figure, the reasons and the UNKNOWNs (shown under "View proof")."""
    r = c["resale"]
    basis = ("owner target " + money(r.get("owner_target")) + " (human-attested) vs system " + money(r.get("system_estimate"))
             if r.get("owner_target") is not None else "system " + money(r.get("system_estimate")))
    fc = c["forecast"].get("final_hammer") or {}
    exp = money(c["net"])
    rl = (f"realized {money(realized['net'])} ({realized['label']})" if realized else "realized: none yet")
    rows = [("Source", c["source"] + (" · DEMO, not a live listing" if c["demo"] else "")), ("Location", f"{c['location']}" + (f", {c['distance']} mi" if c["distance"] is not None else "")),
            ("Current ask/bid", f"{money(c['bid'])}, {c['bids'] if c['bids'] is not None else 'UNKNOWN'} bids, {c['hours_left'] if c['hours_left'] is not None else 'UNKNOWN'} h left"),
            ("All-in cost", money(c["all_in"])), ("Paperwork", c["paperwork"]), ("Repair / transport", f"{money(c['repair'])} / {money(c['transport'])}"),
            ("Resale basis", basis), ("Expected net", exp), ("Days to cash", c["days"] if c["days"] is not None else "UNKNOWN"),
            ("Profit per day / hour", f"{money(c['ppd'])} / {money(c['pph'])}"), ("Demand", c["demand"]), ("Confidence", c["confidence"]),
            ("Max bid", f"{money(c['max_bid'])}" + (f" (bound by {c['max_bid_binding']})" if c["max_bid_binding"] else "")),
            ("Bidder activity / final-price FORECAST", f"{c['bids'] if c['bids'] is not None else 'UNKNOWN'} bids; " + (f"{money(fc.get('low'))} to {money(fc.get('high'))}, expected {money(fc.get('expected'))} (forecast, not observed)" if fc else "UNKNOWN")),
            ("Capital tied up / at risk", f"{money(c['tied_up'])} / {money(c['at_risk'])}"),
            ("Comps", f"{c['sold_comps']} sold, {c['asking_comps']} asking-only (asking never counts as sold)"), ("Expected vs realized", f"expected {exp}; {rl}")]
    why = "".join(f"<li>{e(x)}</li>" for x in c["reasons"] + [f"UNKNOWN input: {u}" for u in c["unknowns"]])
    return (f"<p class='small'>{e(c['note'])}. BUY and bids stay owner-gated. DRY-RUN.</p><dl>{''.join(_row(*x) for x in rows)}</dl>"
            f"{'<ul class=small>' + why + '</ul>' if why else ''}")


def render_deal_card(c: dict, realized: dict | None = None) -> str:
    """One deal as a decision (full detail). DEMO lots carry a DEMO label and no link."""
    return (f"<div class='card deal' id='deal-{e(c['id'])}'><h2>{e(c['title'])} <span class='badge v-{'YES' if c['action']=='BUY' else 'NO' if c['action']=='PASS' else 'MAYBE'}'>{e(c['action'])}</span></h2>"
            f"{proof_html(c, realized)}</div>")


# ---------------------------------------------------------------- the ledger
class ResaleError(ValueError):
    pass


def _money_in(v, name, positive=True):
    try:
        x = Decimal(str(v or "").replace(",", "").lstrip("$").strip())
    except InvalidOperation:
        raise ResaleError(f"{name}: type a plain number") from None
    if not x.is_finite() or x < 0 or x > MAX_MONEY or (positive and x == 0) or x.as_tuple().exponent < -2:
        raise ResaleError(f"{name}: use a positive amount under {MAX_MONEY:,} with at most two decimals")
    return float(x)


def _text(v, name, required=True):
    s = " ".join(str(v or "").split())
    if required and not s:
        raise ResaleError(f"{name} is required")
    if len(s) > MAX_TEXT:
        raise ResaleError(f"{name} is too long (max {MAX_TEXT})")
    return s


class Book:
    """In-memory DRY-RUN resale ledger with a receipt for every step."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.receipts: list[dict] = []
        self.snapshot: dict[str, str] = {}  # last shown action per deal, for "what changed"

    def _receipt(self, item, kind, amount, note, by):
        r = {"id": f"rcpt_{len(self.receipts) + 1:04d}", "item_id": item["id"], "kind": kind, "amount": amount, "note": note, "by": by,
             "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "simulated": item["simulated"], "dry_run": True}
        self.receipts.append(r)
        return r

    def intake(self, f: dict, by: str, deal_id=None, expected_net=None):
        title = _text(f.get("title"), "Item")
        paid = _money_in(f.get("paid"), "Amount paid") if f.get("paid") else 0.0
        iid = "inv_" + secrets.token_hex(4)
        it = {"id": iid, "title": title, "stage": "intake", "paid": paid, "photos": [], "listing": "", "demand": "", "ask": None,
              "simulated": f.get("real") != "1", "expected_net": expected_net, "deal_id": deal_id, "sale": None}
        self.items[iid] = it
        self._receipt(it, "intake", paid, f"intake: {title}", by)
        return it

    def advance(self, iid: str, f: dict, by: str):
        it = self.items.get(iid)
        if it is None:
            raise ResaleError("no such item")
        step = f.get("step")
        nxt = {"photos": "intake", "listing": "photos", "listed": "listing", "sold": "listed"}
        if step not in nxt:
            raise ResaleError("unknown step")
        if it["stage"] != nxt[step]:
            raise ResaleError(f"cannot do '{step}' while the item is at '{it['stage']}'; order is {' -> '.join(STAGES)}")
        if step == "photos":
            refs = [_text(x, "Photo reference") for x in str(f.get("photos") or "").splitlines() if x.strip()][:12]
            if not refs:
                raise ResaleError("add at least one photo reference (file name or note)")
            it["photos"] = refs
            self._receipt(it, "photos", None, f"{len(refs)} photo reference(s), unverified", by)
        elif step == "listing":
            it["listing"] = _text(f.get("listing"), "Listing text")
            it["demand"] = _text(f.get("demand"), "Buyer-demand note", required=False) or "UNKNOWN"
            it["ask"] = _money_in(f.get("ask"), "Asking price")
            self._receipt(it, "listing_prepared", it["ask"], "listing prepared (not published; DRY-RUN)", by)
        elif step == "listed":
            self._receipt(it, "marked_listed", it["ask"], "marked listed by owner; the system published nothing", by)
        else:
            price, fees = _money_in(f.get("price"), "Sold price"), _money_in(f.get("fees") or "0.00", "Fees", positive=False)
            note = _text(f.get("receipt"), "Receipt note (buyer/date/method)")
            it["sale"] = {"price": price, "fees": fees, "net": round(price - fees - it["paid"], 2), "note": note}
            it["receipt_id"] = self._receipt(it, "sale", price, note, by)["id"]
        it["stage"] = step
        return it

    def realized(self) -> dict:
        sold = [i for i in self.items.values() if i["stage"] == "sold"]
        earned = sum(i["sale"]["net"] for i in sold if not i["simulated"])
        sim = sum(i["sale"]["net"] for i in sold if i["simulated"])
        return {"earned": round(earned, 2), "simulated": round(sim, 2), "n_earned": sum(1 for i in sold if not i["simulated"]),
                "n_simulated": sum(1 for i in sold if i["simulated"])}

    def open_cost(self) -> float:
        return sum(i["paid"] for i in self.items.values() if i["stage"] != "sold")


def sale_label(it: dict) -> str:
    return "SIMULATED, not earned" if it["simulated"] else "EARNED (owner-recorded, receipted)"


def utcnow_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def control_strip(book: Book, cards: list[dict], approvals: int | None) -> str:
    tied = book.open_cost()
    rz = book.realized()
    exp = sum(c["net"] for c in cards if c["net"] is not None and c["action"] != "PASS")
    closing = [c for c in cards if c["hours_left"] is not None and c["hours_left"] <= 48]
    paper = [c for c in cards if c["paperwork"].startswith(("bill_of_sale", "no_title", "salvage"))]
    stats = [("DEMO capital available", money(max(0.0, PRINCIPAL + rz["earned"] - tied))), ("Capital tied up", money(tied)),
             ("Inventory", sum(1 for i in book.items.values() if i["stage"] != "sold")),
             ("Expected profit (open deals)", money(exp)), ("Realized profit (earned)", money(rz["earned"])),
             ("Simulated profit (NOT earned)", money(rz["simulated"])), ("Auctions closing ≤48h", len(closing)),
             ("Approvals waiting", approvals if approvals is not None else "UNKNOWN"), ("Watchlist", sum(1 for c in cards if c["action"] == "WATCH")),
             ("Pickups to arrange", sum(1 for i in book.items.values() if i["stage"] == "intake")), ("Paperwork open", len(paper)),
             ("Receipts", len(book.receipts))]
    cells = "".join(f"<td><span class='small mut'>{e(k)}</span><br><b>{e(v)}</b></td>" for k, v in stats)
    return (f"<div class='card' id='control-strip'><table><tr>{cells}</tr></table>"
            f"<p class='small mut'><b>DEMO bankroll {money(PRINCIPAL)}</b> (source: dry-run ledger, not real cash; as of {e(utcnow_iso())}). "
            "Real cash on hand: UNKNOWN until you enter it on My numbers. No recommendation is made from a demo balance. "
            "Simulated sales never count as earned.</p></div>")


def rank(cards: list[dict]) -> list[dict]:
    order = {"BUY": 0, "WATCH": 1, "PASS": 2}
    return sorted(cards, key=lambda c: (order[c["action"]], -(c["net"] if c["net"] is not None else -1e9), c["id"] or ""))


def render_hunt(cards: list[dict], changed: list[str], full: bool = True) -> str:
    """Michael's Morning Money Hunt shape."""
    ranked = rank(cards)
    live = [c for c in ranked if c["action"] != "PASS"]
    best = live[0] if live else None
    bottom = (f"{len(live)} deal(s) worth a look, {len(ranked) - len(live)} rejected. Best expected net: {money(best['net'])} on {best['title']} "
              f"({best['action']}, confidence {best['confidence']})." if best else "Nothing worth a look today; do not spend.")
    table = "".join(f"<tr><td>{i}</td><td><a href='#deal-{e(c['id'])}'>{e(c['title'])}</a></td><td>{e(c['action'])}</td><td class='num'>{money(c['net'])}</td>"
                    f"<td class='num'>{e(c['days'] if c['days'] is not None else 'UNKNOWN')}</td><td class='num'>{money(c['max_bid'])}</td></tr>"
                    for i, c in enumerate(ranked, 1))
    out = [f"<div class='card' id='hunt'><h2>Morning Money Hunt</h2><p><b>Bottom line:</b> {e(bottom)}</p>"
           f"<table><tr><th>#</th><th>Item</th><th>Action</th><th>Expected net</th><th>Days to cash</th><th>Max bid</th></tr>{table}</table></div>"]
    if full:
        for c in ranked:
            risk = "; ".join(c["reasons"]) or "none stated"
            out.append(f"<div class='card'><h3>{e(c['title'])}</h3><p class='small'><b>Source</b> {e(c['source'])} · <b>Economics</b> all-in {money(c['all_in'])}, "
                       f"net {money(c['net'])}, {money(c['ppd'])}/day · <b>Travel</b> {e(c['location'])}{'' if c['distance'] is None else f', {c['distance']} mi'}, transport {money(c['transport'])} · "
                       f"<b>Time to cash</b> {e(c['days'] if c['days'] is not None else 'UNKNOWN')} d · <b>Repair</b> {money(c['repair'])} · <b>Risk</b> {e(risk)} · "
                       f"<b>Confidence</b> {e(c['confidence'])} · <b>Action today</b> {e(c['action'])}: {e(c['note'])}</p></div>")
    rej = [c for c in ranked if c["action"] == "PASS"]
    out.append("<div class='card'><p><b>What changed:</b> " + (e("; ".join(changed)) if changed else "no change since the last look (or no earlier look: UNKNOWN)") + "</p>"
               "<p><b>What was rejected:</b> " + (e("; ".join(f"{c['title']} ({c['reasons'][0] if c['reasons'] else 'expected net not positive'})" for c in rej)) or "nothing") + "</p>"
               "<p><b>Today's best move:</b> " + (e(f"{best['action']} {best['title']}: " + ("get your approval before any bid" if best["action"] == "BUY" else f"watch; max bid {money(best['max_bid'])}")) if best else "keep your cash") + "</p></div>")
    return "".join(out)


def changes(book: Book, cards: list[dict]) -> list[str]:
    out = [f"{c['title']}: {book.snapshot[c['id']]} -> {c['action']}" for c in cards if c["id"] in book.snapshot and book.snapshot[c["id"]] != c["action"]]
    book.snapshot.update({c["id"]: c["action"] for c in cards})
    return out


def render_workflow(book: Book, cards: list[dict], csrf: str, pin_set: bool, flash_bad: str | None = None) -> str:
    pin = "<label>PIN<input name='pin' type='password' autocomplete='off' required></label>"
    if not pin_set:
        return "<div class='card'><p class='bad'>Step-up not configured (MBOS_OPERATOR_PIN unset); resale changes are refused (fail-closed).</p></div>"
    tok = f"<input type='hidden' name='csrf' value='{e(csrf)}'>"
    opts = "".join(f"<option value='{e(c['id'])}'>{e(c['title'])}</option>" for c in cards)
    add = (f"<form method='post' action='/resale/add' class='card'><h2>Inventory intake</h2>{tok}<label>Item<input name='title' maxlength='{MAX_TEXT}' required></label>"
           f"<label>Paid ($)<input name='paid' inputmode='decimal'></label><label>From deal<select name='deal'><option value=''>none</option>{opts}</select></label>"
           f"<label><input type='checkbox' name='real' value='1' style='width:auto'> This is a real purchase (leave unticked for a simulation)</label>{pin}<button>Add to inventory</button></form>")
    rows = []
    for it in book.items.values():
        s = it["stage"]
        form = {"intake": "<label>Photo refs (one per line)<textarea name='photos' rows='2'></textarea></label>",
                "photos": "<label>Listing text<textarea name='listing' rows='2'></textarea></label><label>Buyer-demand note<input name='demand'></label><label>Asking ($)<input name='ask' inputmode='decimal'></label>",
                "listing": "<p class='small'>Mark it listed once YOU have posted it (the system publishes nothing).</p>",
                "listed": "<label>Sold price ($)<input name='price' inputmode='decimal'></label><label>Fees ($)<input name='fees' value='0.00'></label><label>Receipt note<input name='receipt'></label>"}.get(s)
        nxt = {"intake": "photos", "photos": "listing", "listing": "listed", "listed": "sold"}.get(s)
        act = (f"<form method='post' action='/resale/{e(it['id'])}/advance'>{tok}<input type='hidden' name='step' value='{nxt}'>{form}{pin}<button>Record: {nxt}</button></form>"
               if nxt else f"<p>Sold for {money(it['sale']['price'])}; net {money(it['sale']['net'])} <b>({e(sale_label(it))})</b>; receipt {e(it['receipt_id'])}; "
                           f"expected {money(it['expected_net'])} vs realized {money(it['sale']['net'])}.</p>")
        rows.append(f"<div class='card' id='{e(it['id'])}'><h3>{e(it['title'])} <span class='badge'>{e(s)}</span> {'<span class=lbl>SIMULATED</span>' if it['simulated'] else ''}</h3>"
                    f"<p class='small'>Paid {money(it['paid'])} · photos {len(it['photos'])} · demand {e(it['demand'] or 'UNKNOWN')} · listing {e(it['listing'][:120] or 'none')}"
                    f"{'' if it['ask'] is None else ' · ask ' + money(it['ask'])}</p>{act}</div>")
    rc = "".join(f"<tr><td>{e(r['id'])}</td><td>{e(r['item_id'])}</td><td>{e(r['kind'])}</td><td class='num'>{money(r['amount']) if r['amount'] is not None else '-'}</td>"
                 f"<td>{e(r['note'])}</td><td>{'SIMULATED' if r['simulated'] else 'REAL'}</td><td>{e(r['at'])}</td></tr>" for r in book.receipts)
    rz = book.realized()
    acct = (f"<div class='card'><h2>Realized-profit accounting</h2><p>Earned: <b>{money(rz['earned'])}</b> ({rz['n_earned']} sale(s), real and receipted). "
            f"Simulated: {money(rz['simulated'])} ({rz['n_simulated']}), <b>not earned</b>.</p>"
            f"<table><tr><th>Receipt</th><th>Item</th><th>Kind</th><th>Amount</th><th>Note</th><th>Mode</th><th>At</th></tr>{rc}</table></div>")
    return add + "".join(rows) + acct
