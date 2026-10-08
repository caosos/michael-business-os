"""A-40: audit fixes on a real lane D PG16 (worker + owner logins): idempotent lane provenance (F-91), attestation with human provenance,
the funded capital ledger as scoring/card context (F-96), the comps-inbox watcher (F-92), bootstrap releasing the initial freeze (F-89)."""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import asdict

import pytest
import sqlalchemy as sa

from mbos import card as cardmod, config, spine_d
from mbos.config import Settings
from mbos.db.engine import engine_for
from mbos.ids import new_id
from mbos.inbox import InboxWatcher
from mbos.reference.fixture_adapter import FixtureSourceAdapter
from mbos.runtime import Components
from tests.helpers import lane_d
from tests.helpers.common import FIXTURE, ROOT


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    pgserver = pytest.importorskip("pgserver")
    src = tmp_path_factory.mktemp("a40-src")
    lane_d.extract(src)
    server = pgserver.get_server(str(tmp_path_factory.mktemp("a40-pg")), cleanup_mode="stop")
    try:
        app, sysu, owner = lane_d.build_as_worker(server, src, "mbos_a40")
        config.configure(Settings(database_url=app, system_database_url=sysu, owner_database_url=owner, state_backend="lane_d"))
        yield {"app": engine_for(app), "owner": engine_for(owner), "app_url": app}
    finally:
        config._override = None
        config.settings.cache_clear()
        server.cleanup()


@pytest.fixture(scope="module")
def item_id(db):
    comps = Components().with_defaults("lane_d")
    raw = next(r for r in FixtureSourceAdapter(FIXTURE, name="fixture").fetch() if r.source_listing_id == "FIX-TRAILER-1")
    with db["app"].begin() as c:
        return spine_d.ingest(c, asdict(raw), asdict(comps.normalizer.normalize(raw)), "fixture", "0.1.0", comps)["item_id"]


def test_lane_provenance_is_idempotent_for_identical_content(db):
    doc = {"provenance_id": new_id("prov"), "created_at": "2026-10-08T12:00:00Z", "actor_type": "system",
           "agent_name": "agent-03-economics", "basis": "INFERENCE", "tool_name": "t", "tool_version": "1"}
    with db["app"].begin() as c:
        assert spine_d.record_lane_provenance(c, doc) == doc["provenance_id"]
    with db["app"].begin() as c:  # a second `mbos recheck` re-attaches the same record
        assert spine_d.record_lane_provenance(c, copy.deepcopy(doc)) == doc["provenance_id"]
    with db["app"].begin() as c, pytest.raises(ValueError):
        spine_d.record_lane_provenance(c, {**doc, "tool_version": "2"})


def test_attestation_is_stored_with_human_provenance_and_visible_to_lane_c(db, item_id):
    with db["owner"].begin() as c:  # D-29: the OWNER login only (the workflow login is refused, see below)
        e = spine_d.record_attestation(c, item_id, "title_in_hand", "Seller has the title; I saw it Tuesday", "michael")
        again = spine_d.record_attestation(c, item_id, "title_in_hand", "Seller has the title; I saw it Tuesday", "michael")
    assert again == e
    with db["app"].connect() as c:
        item = spine_d.read_item(c, item_id)  # what lane C's research/score steps are handed
        prov = c.execute(sa.text("SELECT to_jsonb(p) FROM mbos.provenance p WHERE provenance_id = :p"), {"p": e["provenance_id"]}).scalar_one()
    mine = [r for r in item["research"] if r["field"] == "attestation:title_in_hand"]
    assert len(mine) == 1 and mine[0]["basis"] == "FACT" and mine[0]["source_uri"] == "human:michael"
    assert prov["actor_type"] == "human" and prov["human_actor"] == "michael"
    with db["owner"].begin() as c, pytest.raises(ValueError):
        spine_d.record_attestation(c, item_id, "", "x", "michael")
    with db["app"].begin() as c, pytest.raises(sa.exc.DBAPIError):  # the workflow login cannot attest
        spine_d.record_attestation(c, item_id, "scope_verified", "forged", "michael")


def test_funded_ledger_reaches_scoring_and_the_card(db):
    from mbos.adapters.ledger import LedgerContext

    src = LedgerContext(db["app_url"])
    assert src() == {}  # unfunded = UNKNOWN, never "0 available"
    with db["owner"].begin() as c:
        pid = c.execute(sa.text("SELECT mbos.record_provenance(CAST(:d AS jsonb))"), {"d": json.dumps({
            "provenance_id": new_id("prov"), "created_at": "2026-10-08T12:00:00Z", "actor_type": "human",
            "human_actor": "michael", "basis": "FACT", "tool_name": "test", "tool_version": "1"})}).scalar_one()
        c.execute(sa.text("SELECT mbos.capital_fund(500::numeric, CAST(:a AS jsonb), 'owner bankroll', :p, 'a40-fund')"),
                  {"a": json.dumps({"type": "human", "id": "michael"}), "p": [pid]})
    assert src() == {"available_to_deploy": 500.0}

    pytest.importorskip("mbos_economics")
    from mbos.adapters.economics import EconomicsEngineScorer

    item = json.loads((ROOT / "docs/research/contracts/examples/item-service-drywall.example.json").read_text())
    plain, funded = EconomicsEngineScorer().score(item), EconomicsEngineScorer(context_source=src).score(item)
    assert plain.inputs_hash != funded.inputs_hash  # the ledger figure is part of the scored inputs
    item["economics"] = {**item["economics"], "context": {"available_to_deploy": 500.0}}
    profile = cardmod.load_profile()
    profile["current_cash_context"] = {"value": None}
    f = cardmod._velocity_fields(item, item["economics"], profile, {})["current_cash_context"]
    assert f["value"] == 500.0 and f["basis"] == "FACT"
    del item["economics"]["context"]
    assert cardmod._velocity_fields(item, item["economics"], profile, {})["current_cash_context"]["value"] == "UNKNOWN"


def test_inbox_watcher_rechecks_only_when_the_inbox_changes(tmp_path):
    calls = []
    w = InboxWatcher(tmp_path, lambda: ["itm_1"], lambda ids: calls.append(ids) or ["wf"])
    assert w.tick() == [] and not calls                       # empty inbox, nothing to do
    (tmp_path / "c1.json").write_text("{}")
    assert w.tick() == ["wf"] and calls == [["itm_1"]]
    assert w.tick() == [] and len(calls) == 1                 # unchanged
    (tmp_path / "c2.json").write_text("{}")
    assert w.tick() == ["wf"] and len(calls) == 2
