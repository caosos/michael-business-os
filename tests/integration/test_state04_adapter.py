"""A-01 phase 1: drive a full flip lifecycle through Agent 04's canonical state API (R1), at 04's PUSHED head.

04's `state/` tree is extracted read-only with `git archive` (never merged); its own roles.sql + migrator
build a fresh database on an isolated pgserver PostgreSQL 16. Then `mbos.adapters.state04.Pg04Ledger` writes
provenance, item, scores, action request, approval, dry-run execution and outcome — and we check:
  * 04's own verify_chain passes, every exported document conforms to the frozen v1.0.0 contracts;
  * ADR-0010 (D-02): the exported chain verifies with the pure-Python reference. strict xfail until 04
    lands D-02 — it then XPASSes, which FAILS this suite on purpose so the coordinator flips it to a hard gate.
"""

from __future__ import annotations

import importlib
import io
import os
import subprocess
import sys
import tarfile

import pytest
import sqlalchemy as sa

from mbos.adapters.state04 import Pg04Ledger
from mbos.contracts import schemas
from mbos.db.engine import engine_for
from mbos.hashing import reference, sha256_of
from tests.helpers.common import ROOT

REF = os.environ.get("MBOS_STATE04_REF", "origin/research/agent-04-state")
SYS = {"type": "system", "id": "agent-01-coordinator"}
MICHAEL = {"type": "human", "id": "michael"}


def _extract(ref: str, dest) -> str:
    sha = subprocess.run(["git", "rev-parse", "--short", ref], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    tar = subprocess.run(["git", "archive", ref, "state"], cwd=ROOT, capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(dest, filter="data")
    return sha


@pytest.fixture(scope="module")
def db04(tmp_path_factory):
    pgserver = pytest.importorskip("pgserver")
    src = tmp_path_factory.mktemp("lane-d-src")
    sha = _extract(REF, src)
    server = pgserver.get_server(str(tmp_path_factory.mktemp("pg04")), cleanup_mode="stop")
    server.psql((src / "state/bootstrap/roles.sql").read_text())
    server.psql("CREATE DATABASE mbos04 OWNER mbos_owner;")
    url = server.get_uri().replace("/postgres?", "/mbos04?")
    sys.path.insert(0, str(src / "state"))
    try:
        migrate = importlib.import_module("mbos_state.migrate")
        migrate.migrate(url, log=lambda *_: None)
    finally:
        sys.path.remove(str(src / "state"))
        for m in [m for m in sys.modules if m.startswith("mbos_state")]:
            del sys.modules[m]
    engine = engine_for(url)
    engine.lane_d_commit = sha
    yield engine
    engine.dispose()
    server.cleanup()


@pytest.fixture(scope="module")
def lifecycle(db04):
    """A complete dry-run flip lifecycle written ONLY through 04's API."""
    L = Pg04Ledger()
    with db04.begin() as c:
        p_src = L.record_provenance(c, actor_type="agent", agent_name="agent-02-opportunity", basis="FACT",
                                    source_uri="https://example.invalid/cl/trailer-6x12", fetched_at="2026-10-07T12:00:00Z")
        item = {"schema_version": "1.0.0", "type": "flip", "category": "trailer", "state": "NORMALIZED",
                "created_at": "2026-10-07T12:00:00Z", "dedup_key": "trailer|750|conway|a01",
                "sources": [{"source": "craigslist", "source_listing_id": "A01-1", "url": "https://example.invalid/cl/trailer-6x12",
                             "ingestion_method": "rss", "first_seen_at": "2026-10-07T12:00:00Z", "provenance_id": p_src,
                             "raw_ref": sha256_of({"raw": "listing"})}],
                "normalized": {"title": "6x12 enclosed trailer", "price": {"amount": 950.0, "currency": "USD", "type": "fixed"}},
                "provenance_ids": [p_src]}
        item_id = L.create_item(c, item, SYS, "discovered + normalized", [p_src], "a01:item:create")
    with db04.begin() as c:
        p_sc = L.record_provenance(c, actor_type="system", basis="INFERENCE", tool_name="mbos_economics.engine", tool_version="0.1.0")
        L.transition_item(c, item_id, "RESEARCHING", SYS, "research", [p_sc], "a01:item:research")
        L.transition_item(c, item_id, "SCORED", SYS, "scored", [p_sc], "a01:item:scored")
        L.patch_item(c, item_id, {"scores": {"scorecard_id": "scr_01JA0000000000000000000A01", "inputs_hash": sha256_of({"x": 1}),
                                             "scorecard": {"scoring_config_version": "2026.10.1", "derived": {}, "sub_scores": {},
                                                           "composite": 70, "decision": "YES", "reasons": ["fixture"]}}},
                     "SCORE_RECORDED", SYS, "scorecard recorded", [p_sc], "a01:item:score")
        L.transition_item(c, item_id, "RECOMMENDED", SYS, "recommended YES", [p_sc], "a01:item:recommended")
        payload = {"capability": "comms.email.send", "summary": "Ask seller about floor; offer $800 (DRY-RUN)", "offer": 800.0}
        areq_id = L.propose_action(c, {"item_id": item_id, "created_at": "2026-10-07T12:05:00Z", "proposed_by": "agent-01-coordinator",
                                       "capability": "comms.email.send", "category": "email", "payload": payload,
                                       "payload_hash": sha256_of(payload), "idempotency_key": "act:a01", "reversibility": "irreversible",
                                       "untrusted_inputs_present": True, "tier": 0, "expires_at": "2099-01-01T00:00:00Z",
                                       "estimated_cost": {"amount": 0, "currency": "USD"}, "provenance_ids": [p_sc]},
                                   SYS, "propose first contact", "a01:areq:propose")
        L.set_action_status(c, areq_id, "classified", "POLICY_DECIDED", SYS, "PDP tier 0", [p_sc], "a01:areq:classified",
                            extra={"policy_decision_ref": "mvp-tier0"})
        L.set_action_status(c, areq_id, "pending_approval", "APPROVAL_REQUESTED", SYS, "to Michael", [p_sc], "a01:areq:pending")
        L.transition_item(c, item_id, "AWAITING_APPROVAL", SYS, "awaiting Michael", [p_sc], "a01:item:awaiting")
    with db04.begin() as c:
        appr_id = L.record_approval(c, {"action_request_id": areq_id, "decision": "YES", "decider": "michael",
                                        "channel": "cli", "payload_hash_seen": sha256_of(payload), "scope": "once",
                                        "auth_context": {"method": "test", "step_up": True}}, MICHAEL, "Michael said YES",
                                    "a01:approval:yes")
        p_gw = L.record_provenance(c, actor_type="system", agent_name="action-gateway", basis="FACT", tool_name="gateway",
                                   tool_version="0.1.0", approval_id=appr_id)
        L.transition_item(c, item_id, "APPROVED", MICHAEL, "approved", [p_gw], "a01:item:approved")
        L.transition_item(c, item_id, "ACTING", SYS, "acting (DRY-RUN)", [p_gw], "a01:item:acting")
        L.set_action_status(c, areq_id, "executing", "ACTION_EXECUTING", SYS, "gateway", [p_gw], "a01:areq:executing",
                            extra={"approval_id": appr_id})
        L.set_action_status(c, areq_id, "executed", "ACTION_EXECUTED", SYS, "DRY-RUN executed", [p_gw], "a01:areq:executed",
                            extra={"approval_id": appr_id, "effect": "send",
                                   "effector_response": {"provider": "dry-run", "provider_msg_id": "dry_a01", "status": "simulated", "dry_run": True},
                                   "details": {"kind": "comms", "dry_run": True}})
        L.transition_item(c, item_id, "ACTED", SYS, "acted", [p_gw], "a01:item:acted")
        p_o = L.record_provenance(c, actor_type="human", human_actor="michael", basis="FACT", tool_name="mbos.cli.outcome", tool_version="0.1.0")
        L.record_outcome(c, {"item_id": item_id, "action_request_id": areq_id, "kind": "flip_acquired",
                             "realized": {"total_cost": 825.0}, "provenance_ids": [p_o]}, MICHAEL, "outcome", "a01:outcome")
    return {"item_id": item_id, "areq_id": areq_id, "approval_id": appr_id, "L": L}


def test_lifecycle_on_lane_d_store(db04, lifecycle):
    L = lifecycle["L"]
    with db04.connect() as c:
        assert L.verify_chain(c)["ok"], L.verify_chain(c)
        state = c.execute(sa.text("SELECT state FROM mbos.items WHERE item_id = :i"), {"i": lifecycle["item_id"]}).scalar_one()
        status = c.execute(sa.text("SELECT status FROM mbos.action_requests WHERE action_request_id = :a"),
                           {"a": lifecycle["areq_id"]}).scalar_one()
    assert (state, status) == ("ACTED", "outcome_recorded")


def test_idempotent_replay_returns_original(db04, lifecycle):
    L = lifecycle["L"]
    with db04.begin() as c:
        n0 = c.execute(sa.text("SELECT count(*) FROM mbos.receipts")).scalar_one()
        assert L.record_approval(c, {"action_request_id": lifecycle["areq_id"], "decision": "YES", "decider": "michael",
                                     "channel": "cli", "payload_hash_seen": "sha256:" + "0" * 64, "scope": "once"},
                                 MICHAEL, "replayed", "a01:approval:yes") == lifecycle["approval_id"]
        assert c.execute(sa.text("SELECT count(*) FROM mbos.receipts")).scalar_one() == n0


def test_exported_documents_conform_to_frozen_contracts(db04, lifecycle):
    L = lifecycle["L"]
    with db04.connect() as c:
        receipts = L.export_receipts(c)
        item = L.load_item(c, lifecycle["item_id"])
        areq = L.load_action_request(c, lifecycle["areq_id"])
    errors = [f"receipt {r['seq']}: {e}" for r in receipts for e in schemas.errors("receipt", r)]
    errors += [f"item: {e}" for e in schemas.errors("item", item)]
    errors += [f"areq: {e}" for e in schemas.errors("action-request", areq)]
    assert not errors, errors[:10]
    assert all(r["effector_response"]["dry_run"] for r in receipts if r["type"] == "ACTION_EXECUTED")


@pytest.mark.xfail(strict=True, reason="D-02 pending: Agent 04 ledger not yet on ADR-0010 MBOS-RH-1")
def test_adr0010_lane_d_chain_verifies_with_reference(db04, lifecycle):
    with db04.connect() as c:
        receipts = lifecycle["L"].export_receipts(c)
    ok, msg = reference().verify_chain(receipts)
    assert ok, f"lane D @ {db04.lane_d_commit}: {msg}"


def test_r12_item_edges_match_lane_d(db04):
    from mbos.state_machine import ITEM_TRANSITIONS
    with db04.connect() as c:
        lane_d = {tuple(r) for r in c.execute(sa.text("SELECT from_state, to_state FROM mbos.item_state_transitions"))}
    assert set(ITEM_TRANSITIONS) == lane_d, {"spine_only": set(ITEM_TRANSITIONS) - lane_d, "lane_d_only": lane_d - set(ITEM_TRANSITIONS)}
