"""A-47: an asset Michael already owns (the BBQ trailer) through the production assembly, inside the frozen v1.0.0 contracts.

The Item `type` enum and the card schema are frozen, so no new type or card section is added. An owned asset is an Item of
type `flip` from source `owned-intake`; Michael's intake answers are its `research[]` entries `owned:*` (C-30 inputs, `mbos_economics.owned_asset`). The lane C
enricher attaches the five-path comparison as the card's `value_add_plan.plan` (an object datum, INFERENCE) and the card lists every
missing input under `unknowns`. Only what Michael stated becomes an input; nothing is invented, nothing is marked verified.
Pure; DRY-RUN; nothing here contacts, spends or publishes.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

_ENGINE_BASIS = {"seller_stated": "FACT", "system_inferred": "INFER"}  # FACT = "stated by Michael"; never verified
_SAFETY = ("tires", "structure", "suspension", "hubs_bearings", "lights_wiring", "burners_work")
_RANGES = {"historical_basis_usd": "historical_basis_usd", "minimal_rehab_cash": "minimal:cash", "themed_rehab_cash": "themed:cash"}
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


SOURCE = "owned-intake"


def is_owned(item: dict) -> bool:
    src = item.get("sources") or [{}]
    return item.get("type") == "flip" and isinstance(src[0], dict) and src[0].get("source") == SOURCE


def _range(text: Any) -> Optional[dict]:
    n = [float(x.replace(",", "")) for x in _NUM.findall(str(text))]
    return {"low": min(n[:2]), "high": max(n[:2])} if n else None


def answers_to_inputs(draft: dict) -> list[tuple[str, Any, str]]:
    """(field, value, basis) for each intake answer Michael gave that C-30 can use. An UNKNOWN or unmapped answer stays missing, so it
    is named UNKNOWN downstream. FACT here means 'stated by Michael', never verified."""
    out = []
    for key, a in draft["answers"].items():
        basis = _ENGINE_BASIS.get(a["basis"])
        if basis is None:
            continue
        if key in _RANGES:
            val = _range(a["value"])
            if val is None:
                continue
            out.append(("owned:" + _RANGES[key], val, basis))
        elif key == "past_tow" or key in _SAFETY:
            out.append(("owned:" + key, a["value"], basis))
    return out


def ingest_pair(asset_id: str, draft: dict, now: str) -> tuple[dict, dict]:
    """(raw, normalized) for `spine.ingest`: the owned asset enters the same spine as any Item. `now` is RFC 3339."""
    title = (draft.get("title") or "Owned asset")[:120]
    raw = {"source": SOURCE, "source_listing_id": asset_id, "url": f"owned://{asset_id}", "fetched_at": now,
           "ingestion_method": "manual", "tos_risk": "low", "payload": {"title": title, "answers": draft["answers"]}}
    norm = {"type": "flip", "category": "trailer", "dedup_key": f"owned:{asset_id}",
            "normalized": {"title": title, "condition": "used", "listing_status": "active"}}
    return raw, norm


def attach_inputs(conn: Any, item_id: str, draft: dict, author: str) -> int:
    """Record Michael's intake answers on the Item as `research[]` (field `owned:*`; the value and who entered it ride in `finding`,
    because the frozen research entry has no value field), cited to one human provenance record. Returns entries added."""
    from mbos import ledger

    inputs = answers_to_inputs(draft)
    if not inputs:
        return 0
    item = ledger.load_item(conn, item_id)
    pid = ledger.record_provenance(conn, actor_type="human", human_actor=author, basis="FACT", source_uri=f"owned://{item_id}/intake",
                                   fetched_at=ledger.now_iso())
    keep = [r for r in item.get("research") or [] if not str(r.get("field", "")).startswith("owned:")]  # latest answers replace earlier ones
    new = [{"finding": json.dumps({"value": v, "entered_by": author}, sort_keys=True), "field": f,
            "basis": "FACT" if b == "FACT" else "INFERENCE", "provenance_id": pid} for f, v, b in inputs]
    ledger.update_item(conn, item_id, patch={"research": keep + new}, intent="owned-asset intake answers recorded (stated, not verified)",
                       provenance_ids=[pid], actor={"type": "human", "id": author})
    return len(new)


def engine_inputs(item: dict) -> list[dict]:
    """The Item's `owned:*` research entries in the form C-30 reads (human-attested: named author, prov_ id)."""
    out = []
    for r in item.get("research") or []:
        if not str(r.get("field", "")).startswith("owned:"):
            continue
        try:
            d = json.loads(r["finding"])
            out.append({"field": r["field"], "value": d["value"], "basis": "FACT" if r["basis"] == "FACT" else "INFER",
                        "entered_by": d["entered_by"], "provenance_id": r["provenance_id"]})
        except (ValueError, KeyError, TypeError):
            continue  # a malformed entry is simply not an input (it will be named UNKNOWN)
    return out


def comparison(item: dict, as_of: str) -> dict:
    from mbos_economics.owned_asset import compare_paths

    return compare_paths({"item_id": item.get("item_id"), "type": "owned_asset", "owned_asset": True, "research": engine_inputs(item)}, as_of)


def plan_value(cmp: dict) -> dict:
    """The card-sized form of the comparison: five paths, the recommendation (or UNKNOWN) and every missing input by exact name."""
    keep = ("path", "incremental_cash", "operator_hours", "days_to_cash", "finished_resale_range", "personal_use_value",
            "net_incremental", "profit_per_incremental_dollar", "profit_per_hour", "risk", "seasonality", "unknowns")
    return {"kind": "owned_asset_five_paths", "decision_basis": cmp["decision_basis"], "sunk_basis": cmp["sunk_basis"],
            "roadworthiness": cmp["roadworthiness"], "recommendation": cmp["recommendation"],
            "paths": [{k: p[k] for k in keep} for p in cmp["paths"]], "unknowns": sorted(set(cmp["unknowns"]) | set(cmp["roadworthiness"]["missing_safety_inputs"])),
            "verified_facts": 0, "dry_run": True}


def value_add_block(item: dict, as_of: str) -> dict:
    """({'block', 'provenance'}) for `spine.record_enrichment(..., 'value_add', ...)`. Deterministic for the same item and as_of."""
    from mbos_economics.canonical import derived_ulid

    from mbos.hashing import sha256_of

    cmp = comparison(item, as_of)
    pid = derived_ulid("prov", as_of, "owned_asset|" + sha256_of(cmp))
    rec = cmp["recommendation"]
    note = ("lean " + rec["path"] if rec["path"] != "UNKNOWN" else "no recommendation: inputs missing") + \
           "; decided on cash from today, sunk basis excluded; Michael's statements, nothing verified"
    block = {"plan": {"value": plan_value(cmp), "basis": "INFERENCE", "provenance_id": pid, "note": note}}
    prov = {"provenance_id": pid, "created_at": as_of, "actor_type": "system", "agent_name": "agent-01-coordinator",
            "basis": "INFERENCE", "tool_name": "mbos.owned_asset", "tool_version": "1.0.0",
            "inputs_used": [{"ref": "item.research[owned:*]", "hash": sha256_of(engine_inputs(item))}]}
    return {"block": block, "provenance": prov}
