"""B-17: NHTSA recalls/complaints → sourced KB candidates; model-year gate (R23) until Agent 03's matcher has years."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest

import mbos_discovery.vehicle_safety as vs
from conftest import FIX, T0
from mbos_discovery.adapter import SearchProfile
from mbos_discovery.adapters import NhtsaAdapter, VehicleQuery
from mbos_discovery.contract import check_provenance
from mbos_discovery.health import HealthBook
from mbos_discovery.http import CallbackTransport, HttpResponse
from mbos_discovery.policy import Disposition, policy_for
from mbos_discovery.rawstore import MemoryRawStore

PROFILE = SearchProfile("vehicles", "flip")
VEH = [VehicleQuery("FIXMOTORS", "ROADSTER", 2012), VehicleQuery("FIXMOTORS", "3", 2012)]


def _run(world, **kw):
    ad = NhtsaAdapter.from_fixture(FIX / "nhtsa", VEH, world.clock)
    raw = MemoryRawStore()
    return ad, raw, vs.collect(ad, PROFILE, raw, HealthBook(), world.clock(), **kw)


def test_policy_and_query_validation():
    assert policy_for("nhtsa").disposition is Disposition.ALLOWED
    for bad in (("", "X", 2012), ("A", "B;drop", 2012), ("A", "B", 1800), ("A", "B", 2100)):
        with pytest.raises(ValueError):
            VehicleQuery(*bad)


def test_live_flag_request_shape_and_read_only(world):
    calls = []
    assert NhtsaAdapter(VEH, transport=CallbackTransport(lambda *a: calls.append(a))).fetch(PROFILE).error.kind == "config" and calls == []
    seen = []
    ad = NhtsaAdapter(VEH[:1], live=True, clock=world.clock,
                      transport=CallbackTransport(lambda m, u, h, b: seen.append((m, u)) or HttpResponse(200, b'{"Count":0,"results":[]}')))
    ad.fetch(PROFILE)
    assert [s[0] for s in seen] == ["GET", "GET"]
    paths = {urlsplit(u).path for _, u in seen}
    assert paths == {"/recalls/recallsByVehicle", "/complaints/complaintsByVehicle"}
    q = parse_qs(urlsplit(seen[0][1]).query)
    assert q == {"make": ["FIXMOTORS"], "model": ["ROADSTER"], "modelYear": ["2012"]}


def test_fixture_run_provenance_and_year_gate(world):
    _, raw, rep = _run(world)
    assert rep.entries == []                                           # nothing ships while the KB has no year matching
    assert rep.sources[0]["recalls"] == 4 and rep.sources[0]["complaint_queries"] == 2
    for r in rep.records.values():
        assert raw.exists(r["raw_ref"]) and r["url"].startswith("https://api.nhtsa.gov/")
        p = rep.provenance[r["provenance_id"]]
        check_provenance(p)
        assert (p["actor_type"], p["basis"], p["source_uri"]) == ("external", "FACT", r["url"])
    by_reason = {}
    for item in rep.review:
        by_reason.setdefault(item["reason"].split(":")[0], []).append(item)
    assert len(by_reason[vs.YEAR_REVIEW.split(":")[0]]) == 5          # 2 fuel/airbag recalls + 3 complaint statistics
    assert any("too short or purely numeric" in i["reason"] for i in rep.review)           # model "3"
    assert any("elementary-advice wording" in i["reason"] for i in rep.review)             # injected text, glance
    c = next(i["candidate_entry"] for i in rep.review if i["recall_id"] == "26V000102" and "candidate_entry" in i)
    assert c["match"] == [{"makes": ["fixmotors"], "models": ["ROADSTER"], "years": [2012]}]
    assert "do not drive until repaired" in c["risk"] and "UNKNOWN" in c["risk"] and "free of charge" in c["risk"]
    assert c["source"]["url"].startswith("https://api.nhtsa.gov/recalls/recallsByVehicle?")


def test_complaint_statistics_are_counts_without_personal_data(world):
    _, _, rep = _run(world)
    stats = {i["candidate_entry"]["id"]: i["candidate_entry"] for i in rep.review
             if i.get("candidate_entry", {}).get("kind") == "known_weakness"}
    # SUSPENSION has 2 < 5 and is not reported; "POWER TRAIN,ENGINE" is NHTSA's list of two components, counted for each
    assert set(stats) == {"nhtsa_complaints_fixmotors_roadster_2012_electrical_system",
                          "nhtsa_complaints_fixmotors_roadster_2012_power_train",
                          "nhtsa_complaints_fixmotors_roadster_2012_engine"}
    el = stats["nhtsa_complaints_fixmotors_roadster_2012_electrical_system"]
    assert "7 consumer complaints" in el["risk"] and "of 14 complaints" in el["risk"] and "2 mention a fire" in el["risk"]
    assert "unverified consumer reports" in el["risk"] and el["evidence"]["complaints"] == 7
    blob = json.dumps(rep.review)
    assert "555-0100" not in blob and "1FIXTUR3E12" not in blob and "narrative" not in blob


def test_flag_admits_entries_that_pass_the_standard(world, monkeypatch):
    monkeypatch.setattr(vs, "KB_SUPPORTS_MODEL_YEARS", True)
    _, _, rep = _run(world)
    ids = {e["id"] for e in rep.entries}
    assert ids == {"nhtsa_26v000101_fixmotors_roadster_2012", "nhtsa_26v000102_fixmotors_roadster_2012",
                   "nhtsa_complaints_fixmotors_roadster_2012_electrical_system",
                   "nhtsa_complaints_fixmotors_roadster_2012_power_train",
                   "nhtsa_complaints_fixmotors_roadster_2012_engine"}
    assert not any("3" == e["match"][0]["models"][0] for e in rep.entries)                    # numeric model still held
    assert all(i["reason"] != vs.YEAR_REVIEW for i in rep.review)
    pytest.importorskip("mbos_economics.valueadd")


def test_admitted_entries_load_in_agent_03(world, monkeypatch, tmp_path):
    vo = pytest.importorskip("mbos_economics.valueadd")
    monkeypatch.setattr(vs, "KB_SUPPORTS_MODEL_YEARS", True)
    _, _, rep = _run(world)
    p = tmp_path / "kb.json"
    p.write_text(json.dumps({"kb_version": "fixture", "kb_format": 1, "entries": [
        {k: v for k, v in e.items() if k != "match"} | {"match": [{"makes": e["match"][0]["makes"], "models": e["match"][0]["models"]}]}
        for e in rep.entries]}))
    assert {e["id"] for e in vo.load_kb(p)["entries"]} == {e["id"] for e in rep.entries}     # passes 03's admission checks


def test_block_freeze_and_determinism(world):
    ad = NhtsaAdapter(VEH, live=True, clock=world.clock, transport=CallbackTransport(lambda *a: HttpResponse(429, b"x")))
    health, raw = HealthBook(), MemoryRawStore()
    vs.collect(ad, PROFILE, raw, health, T0)
    assert vs.collect(ad, PROFILE, raw, health, T0).freeze_requests[0]["capability"] == "discovery.source.nhtsa.read"
    _, _, a = _run(world)
    _, _, b = _run(world)
    assert a.review == b.review
