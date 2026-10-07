"""C-12: replay audit (AT-1 at scale). READ-ONLY.

For every stored, scored Item: recompute ``inputs_hash`` from the stored inputs and stored
``scoring_config_version``, re-run the engine under that config, and compare. Optionally cross-check
the ledger's ``SCORE_RECORDED`` receipts.

Findings are classified so a reviewer can act on them:

In ledger mode (``receipts`` given) every scorecard must have a SCORE_RECORDED receipt whose
``payload_hash`` equals the stored scorecard's MBOS-CJSON-1 hash ("no score without a receipt").

* ``drift`` (fails the audit): the stored record no longer reproduces under rules that should reproduce it:
    - ``inputs_hash``: inputs (or the stored hash) changed after scoring
    - ``config_edited``: the config file for that version no longer has the content that scored it
    - ``config_missing``: the stored config version cannot be loaded
    - ``decision``: same engine version, different verdict
    - ``scorecard``: same engine version, byte replay differs (e.g. a tampered number)
    - ``receipt``: the SCORE_RECORDED receipt does not match the scorecard
* ``receipt_weak`` (reported; fails only with ``strict``): the ledger receipt carries ``inputs_hash`` but no
  ``payload_hash``, so the scorecard content itself is not bound by the ledger.
* ``not_engine_scorecard`` (reported): a scorecard the engine never produced (no engine_version/derived).
* ``engine_change`` (reported, does not fail): an OLDER engine version scored it and the current engine
  reaches a different verdict on identical inputs + config; expected after a ruling, listed for review.

Nothing is written. Loaders read Agent 04's views with SELECT only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import __version__ as ENGINE_VERSION
from .canonical import content_hash, derived_ulid
from .config import CONFIG_DIR, ConfigError, load_config
from .engine import compute, inputs_hash
from .inputs import InputError, build_engine_input
from .replay import replay_item

TOOL_NAME = "mbos_economics.replay_audit"
DRIFT_KINDS = {"inputs_hash", "config_edited", "config_missing", "decision", "scorecard", "receipt", "invalid_input"}


def load_scored_items(conn) -> tuple[list[dict], list[dict]]:
    """Scored Item documents and SCORE_RECORDED receipts from Agent 04's read views (SELECT only)."""
    cur = conn.cursor()
    cur.execute("SELECT doc FROM mbos.v_item_documents WHERE doc ? 'scores' ORDER BY item_id")
    items = [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in cur.fetchall()]
    cur.execute("SELECT doc FROM mbos.v_receipt_documents WHERE doc->>'type' = 'SCORE_RECORDED' ORDER BY seq")
    receipts = [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in cur.fetchall()]
    return items, receipts


def _audit_item(item: dict, receipts_by_item: dict | None, config_dir: Path, strict: bool = False) -> dict:
    scores = item["scores"]
    sc = scores["scorecard"]
    version = sc.get("scoring_config_version")
    produced_by = sc.get("engine_version")
    findings: list[dict] = []

    def add(kind: str, detail: str) -> None:
        findings.append({"kind": kind, "drift": kind in DRIFT_KINDS, "detail": detail})

    if not sc.get("engine_version") or "derived" not in sc or not sc.get("derived"):
        # e.g. a spine fallback card written when inputs were missing: the engine never produced it
        add("not_engine_scorecard", "scorecard was not produced by mbos_economics (no engine_version/derived); "
                                    "nothing to replay")
        return {"item_id": item.get("item_id"), "scorecard_id": scores.get("scorecard_id"), "engine_version": None,
                "config_version": version, "decision": sc.get("decision"), "receipts_matched": 0, "findings": findings}

    try:
        inp = build_engine_input(item)
        recomputed = inputs_hash(inp, version)
    except Exception as e:  # malformed stored input is itself a finding
        add("invalid_input", f"cannot rebuild engine input: {e}")
        return {"item_id": item.get("item_id"), "scorecard_id": scores.get("scorecard_id"), "findings": findings}
    if recomputed != scores["inputs_hash"]:
        add("inputs_hash", f"stored {scores['inputs_hash']} != recomputed {recomputed}")

    try:
        cfg = load_config(version, config_dir)
    except ConfigError as e:
        add("config_missing", str(e))
        cfg = None
    if cfg is not None:
        if sc.get("config_hash") and sc["config_hash"] != cfg.hash:
            add("config_edited", f"config {version} content hash {cfg.hash} != scored-with {sc['config_hash']}")
        try:
            fresh = compute(inp, cfg)
        except InputError as e:
            add("invalid_input", "; ".join(e.problems))
            fresh = None
        if fresh is not None and fresh["decision"] != sc["decision"]:
            if produced_by == ENGINE_VERSION:
                add("decision", f"stored {sc['decision']} != replayed {fresh['decision']} (same engine {produced_by})")
            else:
                add("engine_change", f"engine {produced_by} said {sc['decision']}; engine {ENGINE_VERSION} says "
                                     f"{fresh['decision']} on identical inputs + config {version}")
        if produced_by == ENGINE_VERSION and not any(f["kind"] in ("inputs_hash", "config_edited") for f in findings):
            r = replay_item(item, config_dir)
            if not r["scorecard_match"]:
                add("scorecard", "byte replay differs: " + "; ".join(r["diffs"][:5]))

    matched = 0
    if receipts_by_item is not None:
        # Agent 04 records SCORE_RECORDED with entity = the item; the scorecard is identified by payload_hash.
        mine = receipts_by_item.get(item.get("item_id"), []) + [
            r for r in receipts_by_item.get("__by_scorecard__", {}).get(scores["scorecard_id"], [])]
        want = content_hash(sc)
        strong = [rc for rc in mine if rc.get("payload_hash") == want]
        weak = [rc for rc in mine if not rc.get("payload_hash") and rc.get("inputs_hash") == scores["inputs_hash"]]
        matched = len(strong) + len(weak)
        if not strong and not weak:
            add("receipt", "no SCORE_RECORDED receipt in the ledger matches this scorecard "
                           f"(payload_hash {want}, inputs_hash {scores['inputs_hash']}); "
                           f"{len(mine)} SCORE_RECORDED receipt(s) for the item")
        elif not strong:
            add("receipt_weak" if not strict else "receipt",
                "ledger receipt binds inputs_hash only (no payload_hash), so the scorecard CONTENT is not bound by the "
                "ledger; the writer should add payload_hash = MBOS-CJSON-1 hash of the scorecard")
        for rc in strong:
            if rc.get("inputs_hash") and rc["inputs_hash"] != scores["inputs_hash"]:
                add("receipt", f"receipt {rc.get('receipt_id')} inputs_hash {rc['inputs_hash']} != item {scores['inputs_hash']}")
    return {"item_id": item.get("item_id"), "scorecard_id": scores["scorecard_id"], "engine_version": produced_by,
            "config_version": version, "decision": sc["decision"], "receipts_matched": matched, "findings": findings}


def audit(items: list[dict], *, receipts: list[dict] | None = None, config_dir: Path = CONFIG_DIR,
          audited_at: str | None = None, strict: bool = False) -> dict:
    """Audit every scored Item. Pure apart from reading config files; writes nothing."""
    by_item: dict | None = None
    if receipts is not None:                       # ledger mode: every scorecard must have a matching receipt
        by_item = {"__by_scorecard__": {}}
        for rc in receipts:
            if rc.get("type") != "SCORE_RECORDED":
                continue
            if rc.get("item_id"):
                by_item.setdefault(rc["item_id"], []).append(rc)
            elif rc.get("entity_id"):
                by_item["__by_scorecard__"].setdefault(rc["entity_id"], []).append(rc)
    scored = sorted((i for i in items if i.get("scores")), key=lambda i: str(i.get("item_id")))
    rows = [_audit_item(i, by_item, config_dir, strict) for i in scored]
    drift = [r for r in rows if any(f["drift"] for f in r["findings"])]
    changed = [r for r in rows if any(f["kind"] == "engine_change" for f in r["findings"])]
    body = {
        "engine_version": ENGINE_VERSION,
        "items_seen": len(items), "scorecards_audited": len(rows),
        "ledger_mode": receipts is not None,
        "receipts_matched": sum(r["receipts_matched"] for r in rows),
        "strict": strict,
        "drift_count": len(drift), "engine_change_count": len(changed),
        "weak_receipt_count": sum(1 for r in rows if any(f["kind"] == "receipt_weak" for f in r["findings"])),
        "not_engine_count": sum(1 for r in rows if any(f["kind"] == "not_engine_scorecard" for f in r["findings"])),
        "ok": not drift,
        "rows": rows,
    }
    out = {**body, "report_hash": content_hash(body)}
    if audited_at:
        out["provenance"] = {
            "provenance_id": derived_ulid("prov", audited_at, f"audit|{out['report_hash']}"),
            "created_at": audited_at, "actor_type": "system", "agent_name": "agent-03-economics", "basis": "FACT",
            "tool_name": TOOL_NAME, "tool_version": ENGINE_VERSION,
            "inputs_used": [{"ref": r["scorecard_id"], "hash": next(i["scores"]["inputs_hash"] for i in scored
                                                                     if i["scores"]["scorecard_id"] == r["scorecard_id"])}
                            for r in rows],
        }
    return out
