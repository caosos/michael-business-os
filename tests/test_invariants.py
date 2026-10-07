"""Acceptance F1 + contract conformance: every Item has sources[], every sighting has a
raw_ref that resolves to the retained bytes, and every Item / Provenance validates."""

import json

from mbos_discovery import contract
from mbos_discovery.ids import sha256_ref


def test_every_item_has_sources_and_raw_ref(world):
    world.run()
    assert world.store.items
    for item in world.store.items.values():
        assert item["sources"], item["item_id"]
        for s in item["sources"]:
            assert s["raw_ref"].startswith("sha256:")
            data = world.raw.get(s["raw_ref"])              # retained…
            assert sha256_ref(data) == s["raw_ref"]          # …and content-addressed


def test_items_and_provenance_validate_against_frozen_contracts(world):
    world.run()
    for item in world.store.items.values():
        contract.check_item(item)
    for prov in world.store.provenance.values():
        contract.check_provenance(prov)
        assert prov["source_uri"] and prov["fetched_at"]     # source-URI branch of the anyOf rule
        assert prov["tool_name"].startswith("mbos_discovery.adapters.")


def test_every_sighting_and_item_provenance_resolves(world):
    world.run()
    for item in world.store.items.values():
        for s in item["sources"]:
            assert s["provenance_id"] in world.store.provenance
            assert s["provenance_id"] in item["provenance_ids"]
            prov = world.store.provenance[s["provenance_id"]]
            assert prov["inputs_used"][0]["hash"] == s["raw_ref"]
        for pid in item["provenance_ids"]:
            assert pid in world.store.provenance


def test_both_lanes_present_with_lane_correct_categories(world):
    world.run()
    by_type = {}
    for item in world.store.items.values():
        by_type.setdefault(item["type"], set()).add(item["category"])
    assert {"flip", "service"} <= set(by_type)
    assert {"trailer", "generator", "welder"} <= by_type["flip"]
    assert {"drywall_repair", "assembly", "smart_home_install", "equipment_repair"} <= by_type["service"]


def test_contract_check_rejects_item_without_raw_ref(world):
    world.run()
    item = json.loads(json.dumps(next(iter(world.store.items.values()))))
    del item["sources"][0]["raw_ref"]
    try:
        contract.check_item(item)
    except contract.ContractViolation as e:
        assert "raw_ref" in str(e)
    else:
        raise AssertionError("item without raw_ref passed")


def test_receipt_intents_carry_provenance_and_idempotency(world):
    world.run()
    created = [e for e in world.store.events if e["event"] == "CREATED"]
    assert len(created) == sum(1 for _ in world.store.items)
    for e in world.store.events:
        ri = e["receipt_intent"]
        assert ri["provenance_ids"] and ri["idempotency_key"] and ri["artifact_hashes"] == [e["raw_ref"]]
        assert ri["type"] == "ITEM_STATE_CHANGED"
    assert len({e["receipt_intent"]["idempotency_key"] for e in world.store.events}) == len(world.store.events)


def test_untrusted_text_is_flagged_not_obeyed(world):
    world.run()
    flagged = [i for i in world.store.items.values() if "injection_suspected" in i["normalized"].get("flags", [])]
    assert {i["type"] for i in flagged} == {"flip", "service"}
    for i in flagged:
        assert "needs_review" in i["normalized"]["flags"]
        assert i["state"] == "NORMALIZED"                   # discovery never advances it further
