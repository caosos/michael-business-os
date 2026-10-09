"""A-51: an auction lot (lane B, B-23) scored by lane C's auction / asset model (C-32 `auction`, C-33 `asset_deal`) on the spine.

Inside the frozen v1.0.0 contracts: the lot is an Item of `opportunity_kind` `auction_lot`. What the Item `normalized` object cannot
hold (buyer premium as stated, sales tax, pickup terms, when the bid was observed) and Michael's / research inputs (owner resale target,
pickup and transport cost, hours, days to sell, SOLD and asking comps, repair, cash cap) ride as `research[]` entries `auction:*`, the
value and who entered it in `finding` (as `owned:*` does, A-47). Only Items carrying `auction:*` entries take this path, so every other
Item scores exactly as before. The hammer is the CURRENT bid (observed); the final hammer is only ever a labelled FORECAST.
Pure; DRY-RUN; there is no bid path here or anywhere downstream.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

PREFIX = "auction:"
LOT_FACTS = ("buyer_premium_pct", "sales_tax_pct", "pickup", "rules_url")
INPUTS = ("pickup_cost", "transport_cost", "other_fixed_cost", "labor_hours", "days_to_sell", "pickup_wait_hours", "payout_lag_days",
          "resale_fee_pct", "asset_class", "repair", "parts", "paperwork", "teardown_cost", "teardown_hours", "comps",
          "owner_resale_target", "cash_cap_per_buy")


def conform(raw: dict, norm: dict) -> tuple[dict, dict]:
    """Bridge B-23's output to the frozen Item contract (found by A-51): its fixture adapter reports `ingestion_method` `fixture` and
    `counterparty.role` `auction_house`, neither in the v1.0.0 enums. A fixture file is JSON; an auction house is role `other` (the name
    is kept). Proposed upstream fix: lane 02 emits contract values. Nothing else is changed."""
    raw = {**raw, "ingestion_method": "json"} if raw.get("ingestion_method") == "fixture" else raw
    n = norm.get("normalized") or {}
    cp = n.get("counterparty") or {}
    if cp.get("role") == "auction_house":
        norm = {**norm, "normalized": {**n, "counterparty": {**cp, "role": "other"}}}
    return raw, norm


def research_inputs(item: dict) -> dict[str, Any]:
    """{name: value} from the Item's `auction:*` research entries (latest wins). A malformed entry is simply not an input."""
    out = {}
    for r in item.get("research") or []:
        f = str(r.get("field", ""))
        if f.startswith(PREFIX):
            try:
                out[f[len(PREFIX):]] = json.loads(r["finding"])["value"]
            except (ValueError, KeyError, TypeError):
                continue
    return out


def is_auction(item: dict) -> bool:
    return item.get("opportunity_kind") == "auction_lot" and bool(research_inputs(item))


def _record(conn: Any, item_id: str, entries: list[tuple[str, Any]], entered_by: str, basis: str, prov: dict, intent: str,
            actor: dict) -> int:
    from mbos import ledger

    if not entries:
        return 0
    item = ledger.load_item(conn, item_id)
    pid = ledger.record_provenance(conn, basis=basis, **prov)
    names = {PREFIX + k for k, _ in entries}
    keep = [r for r in item.get("research") or [] if r.get("field") not in names]  # a newer value replaces the older one
    new = [{"finding": json.dumps({"value": v, "entered_by": entered_by}, sort_keys=True), "field": PREFIX + k, "basis": basis,
            "provenance_id": pid} for k, v in entries]
    ledger.update_item(conn, item_id, patch={"research": keep + new}, intent=intent, provenance_ids=[pid], actor=actor)
    return len(new)


def attach_lot(conn: Any, item_id: str, lot: Any) -> int:
    """Record the B-23 lot's own stated terms (`AuctionLot.fields`: value, source, observed_at, basis). UNKNOWN stays missing."""
    f = lot.fields
    seen = f["current_bid"].observed_at
    entries = [(k, f[k].value) for k in LOT_FACTS if k in f and f[k].basis == "FACT"] + [("observed_at", seen)]
    return _record(conn, item_id, entries, "agent-02-opportunity", "FACT",
                   {"actor_type": "agent", "agent_name": "agent-02-opportunity", "source_uri": f["current_bid"].source, "fetched_at": seen},
                   "auction lot terms as stated by the source", {"type": "agent", "id": "agent-02-opportunity"})


def attach_inputs(conn: Any, item_id: str, inputs: dict[str, Any], author: str) -> int:
    """Record Michael's / research inputs (stated, not verified). Unknown keys are refused, never stored."""
    from mbos import ledger

    bad = sorted(set(inputs) - set(INPUTS))
    if bad:
        raise ValueError(f"not auction inputs: {bad}")
    return _record(conn, item_id, sorted(inputs.items()), author, "FACT",
                   {"actor_type": "human", "human_actor": author, "source_uri": f"auction://{item_id}/inputs", "fetched_at": ledger.now_iso()},
                   "auction inputs recorded (stated, not verified)", {"type": "human", "id": author})


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def engine_input(item: dict) -> dict[str, Any]:
    """The `mbos_economics.asset_deal.evaluate` input. Percentages stated by the source become fractions; a missing one stays missing."""
    n = item.get("normalized") or {}
    r = research_inputs(item)
    bid = (n.get("price") or {}).get("amount")
    inp = {k: r[k] for k in INPUTS if k in r and k != "cash_cap_per_buy"}
    inp.update(item_id=item.get("item_id"), hammer_price=bid, current_bid=bid, bid_count=n.get("bid_count"))
    for src, dst in (("buyer_premium_pct", "buyer_premium_pct"), ("sales_tax_pct", "sales_tax_rate")):
        if isinstance(r.get(src), (int, float)) and not isinstance(r.get(src), bool):
            inp[dst] = round(r[src] / 100, 6)
    if n.get("ends_at") and r.get("observed_at"):
        inp["hours_left"] = max(0.0, round((_ts(n["ends_at"]) - _ts(r["observed_at"])).total_seconds() / 3600, 2))
    return {k: v for k, v in inp.items() if v is not None}


def evaluate(item: dict) -> dict:
    from mbos_economics.asset_deal import evaluate as asset_evaluate
    from mbos_economics.asset_deal import load_asset_config

    k = load_asset_config()
    cap = research_inputs(item).get("cash_cap_per_buy")
    if isinstance(cap, (int, float)) and not isinstance(cap, bool) and cap > 0:
        k = {**k, "cash_cap_per_buy": cap}
    return asset_evaluate(engine_input(item), kcfg=k)


def summary(item: dict, out: dict) -> dict:
    """The card-sized decision block: every figure is the engine's (INFERENCE) or the lot's (FACT); missing ones are named."""
    n = item.get("normalized") or {}
    r = research_inputs(item)
    lot = {"current_bid": (n.get("price") or {}).get("amount"), "bid_count": n.get("bid_count"), "closes_at": n.get("ends_at"),
           "buyer_premium_pct": r.get("buyer_premium_pct"), "sales_tax_pct": r.get("sales_tax_pct"), "pickup": r.get("pickup"),
           "observed_at": r.get("observed_at"), "basis": "FACT (as stated by the source)"}
    s = {"kind": "auction_lot_economics", "verdict": out["verdict"], "lot": lot, "hammer_basis": "current bid (observed); not the final price",
         "evidence": out["evidence"], "unknowns": out.get("unknowns", []), "reasons": out.get("reasons", []), "dry_run": True,
         "bid_path": "none (dry-run; bidding stays with Michael)"}
    if out.get("computable"):
        s.update(all_in_cost=out["cost"]["all_in"], cost=out["cost"], extras=out["extras"], net=out["net"], days_to_cash=out["days_to_cash"],
                 profit_per_day=out["profit_per_day"], profit_per_labor_hour=out["profit_per_labor_hour"],
                 capital_tied_up=out["capital_tied_up"], capital_at_risk=out["capital_at_risk"], cash_cap=out["cash_cap"],
                 suggested_max_bid=out["suggested_max_bid"], resale=out["resale"], headline_path=out["headline_path"], flags=out["flags"])
        if out.get("bid_forecast"):
            s["bid_forecast"] = out["bid_forecast"]
    return s


def derived(out: dict) -> dict:
    """The scorecard `derived` figures the card already reads (cash at risk, days to cash, deterministic net / hour)."""
    if not out.get("computable"):
        return {}
    d = {"cash_tied_up": out["capital_tied_up"], "time_to_cash_days": out["days_to_cash"], "net_profit_deterministic": out["net"]["expected"],
         "profit_per_hour_deterministic": out["profit_per_labor_hour"]}
    return {k: v for k, v in d.items() if v is not None}


def max_bid(out: dict) -> Optional[float]:
    return (out.get("suggested_max_bid") or {}).get("max_bid") if out.get("computable") else None


def value_add_block(item: dict) -> Optional[dict]:
    """({'block', 'provenance'}) for `spine.record_enrichment(..., 'value_add', ...)`: the scored auction block on the card's plan.
    None until the Item has been scored on this path. Deterministic for the same scorecard."""
    from mbos_economics.canonical import derived_ulid

    from mbos.hashing import sha256_of

    a = ((item.get("scores") or {}).get("scorecard") or {}).get("auction")
    if not a:
        return None
    as_of = item["created_at"]
    pid = derived_ulid("prov", as_of, "auction_lot|" + sha256_of(a))
    mb = (a.get("suggested_max_bid") or {}).get("max_bid")
    note = (f"machine verdict {a['verdict']}; suggested max bid {mb if mb is not None else 'UNKNOWN'}; the final price is a FORECAST, "
            "not observed; asking comps never count as sales; dry-run, no bid path")
    block = {"plan": {"value": a, "basis": "INFERENCE", "provenance_id": pid, "note": note}}
    prov = {"provenance_id": pid, "created_at": as_of, "actor_type": "system", "agent_name": "agent-01-coordinator",
            "basis": "INFERENCE", "tool_name": "mbos.auction_lot", "tool_version": "1.0.0",
            "inputs_used": [{"ref": "item.scores.scorecard.auction", "hash": sha256_of(a)}]}
    return {"block": block, "provenance": prov}
