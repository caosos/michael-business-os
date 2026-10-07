"""B-17/B-18: NHTSA recalls/complaints → sourced KB entries with model years (Agent 03 C-18)."""

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
VEH2 = [VehicleQuery("FIXMOTORS", "ROADSTER", 2012), VehicleQuery("FIXMOTORS", "ROADSTER", 2013)]


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


def test_fixture_run_entries_with_years_and_review(world):
    _, raw, rep = _run(world)
    assert rep.sources[0]["recalls"] == 4 and rep.sources[0]["complaint_queries"] == 2
    for r in rep.records.values():
        assert raw.exists(r["raw_ref"]) and r["url"].startswith("https://api.nhtsa.gov/")
        p = rep.provenance[r["provenance_id"]]
        check_provenance(p)
        assert (p["actor_type"], p["basis"], p["source_uri"]) == ("external", "FACT", r["url"])
    assert {e["id"] for e in rep.entries} == {
        "nhtsa_26v000101_fixmotors_roadster", "nhtsa_26v000102_fixmotors_roadster",
        "nhtsa_complaints_fixmotors_roadster_2012_electrical_system",
        "nhtsa_complaints_fixmotors_roadster_2012_power_train", "nhtsa_complaints_fixmotors_roadster_2012_engine"}
    for e in rep.entries:                                              # every per-year entry carries years (a bug if not)
        assert e["match"][0]["years"] and all(1950 <= y <= 2035 for y in e["match"][0]["years"])
    reasons = [i["reason"] for i in rep.review]
    assert any("too short or purely numeric" in r for r in reasons)    # model "3" still held
    assert any("elementary-advice wording" in r for r in reasons)      # glance
    assert not any("model-year" in r for r in reasons)                  # the old gate is gone
    c = next(e for e in rep.entries if e["id"] == "nhtsa_26v000102_fixmotors_roadster")
    assert c["match"] == [{"makes": ["fixmotors"], "models": ["ROADSTER"], "years": [2012]}]
    assert "do not drive until repaired" in c["risk"] and "UNKNOWN" in c["risk"] and "free of charge" in c["risk"]
    assert c["source"]["url"].startswith("https://api.nhtsa.gov/recalls/recallsByVehicle?")


def test_one_campaign_across_years_is_one_entry_with_all_years(world):
    ad = NhtsaAdapter.from_fixture(CPSC_FIX := FIX / "nhtsa", VEH2, world.clock, include_complaints=False)
    rep = vs.collect(ad, PROFILE, MemoryRawStore(), HealthBook(), world.clock())
    e = next(x for x in rep.entries if x["id"] == "nhtsa_26v000101_fixmotors_roadster")
    assert e["match"] == [{"makes": ["fixmotors"], "models": ["ROADSTER"], "years": [2012, 2013]}]      # one group
    assert "2012, 2013 Fixmotors ROADSTER recall" in e["risk"]
    assert len([x for x in rep.entries if x["id"].startswith("nhtsa_26v000101")]) == 1


def test_complaint_statistics_are_counts_without_personal_data(world):
    _, _, rep = _run(world)
    stats = {e["id"]: e for e in rep.entries if e["kind"] == "known_weakness"}
    # SUSPENSION has 2 < 5 and is not reported; "POWER TRAIN,ENGINE" is NHTSA's list of two components, counted for each
    assert set(stats) == {"nhtsa_complaints_fixmotors_roadster_2012_electrical_system",
                          "nhtsa_complaints_fixmotors_roadster_2012_power_train",
                          "nhtsa_complaints_fixmotors_roadster_2012_engine"}
    el = stats["nhtsa_complaints_fixmotors_roadster_2012_electrical_system"]
    assert "7 consumer complaints" in el["risk"] and "of 14 complaints" in el["risk"] and "2 mention a fire" in el["risk"]
    assert "unverified consumer reports" in el["risk"] and el["evidence"]["complaints"] == 7
    blob = json.dumps(rep.entries + rep.review)
    assert "555-0100" not in blob and "1FIXTUR3E12" not in blob and "narrative" not in blob


def test_flag_off_holds_entries_for_review_again(world, monkeypatch):
    monkeypatch.setattr(vs, "KB_SUPPORTS_MODEL_YEARS", False)
    _, _, rep = _run(world)
    assert rep.entries == [] and sum("model-year" in i["reason"] for i in rep.review) == 5
    assert all(i["candidate_entry"]["match"][0]["years"] for i in rep.review if "candidate_entry" in i)


def test_entries_load_in_agent_03_and_match_years_correctly(world, tmp_path):
    vo = pytest.importorskip("mbos_economics.valueadd")
    if not hasattr(vo, "match_hits"):
        pytest.skip("Agent 03 engine < 0.11.0 (no model-year matching)")
    ad = NhtsaAdapter.from_fixture(FIX / "nhtsa", VEH2, world.clock)
    rep = vs.collect(ad, PROFILE, MemoryRawStore(), HealthBook(), world.clock())
    path = tmp_path / "kb.json"
    path.write_text(json.dumps({"kb_version": "fixture", "kb_format": 1, "entries": rep.entries}))
    kb = vo.load_kb(path)                                                # years validated by Agent 03's loader
    assert {e["id"] for e in kb["entries"]} == {e["id"] for e in rep.entries}

    def item(title):
        return {"category": "project_vehicle", "normalized": {"title": title}}

    hits, blocked = vo.match_hits(item("2012 Fixmotors Roadster, runs good"), kb)
    assert "nhtsa_26v000101_fixmotors_roadster" in {h["entry"]["id"] for h in hits}
    assert all(h["year_evidence"] for h in hits)                         # the year was read from the listing title
    hits, blocked = vo.match_hits(item("2018 Fixmotors Roadster"), kb)   # uncovered year: no claim
    assert hits == [] and any(b["entry_id"] == "nhtsa_26v000101_fixmotors_roadster" for b in blocked)
    hits, blocked = vo.match_hits(item("Fixmotors Roadster project car"), kb)   # no year: no claim (UNKNOWN)
    assert hits == [] and blocked
    hits, _ = vo.match_hits(item("2012 and 2018 Fixmotors Roadster"), kb)        # every stated year must be covered
    assert hits == []


def test_block_freeze_and_determinism(world):
    ad = NhtsaAdapter(VEH, live=True, clock=world.clock, transport=CallbackTransport(lambda *a: HttpResponse(429, b"x")))
    health, raw = HealthBook(), MemoryRawStore()
    vs.collect(ad, PROFILE, raw, health, T0)
    assert vs.collect(ad, PROFILE, raw, health, T0).freeze_requests[0]["capability"] == "discovery.source.nhtsa.read"
    _, _, a = _run(world)
    _, _, b = _run(world)
    assert a.review == b.review


def test_entry_ids_are_unique_before_the_file_is_written(world):
    """Agent 03's load_kb (0.11.1) refuses duplicate ids and the matcher keys year evidence by id."""
    ad = NhtsaAdapter.from_fixture(FIX / "nhtsa", VEH2, world.clock)
    rep = vs.collect(ad, PROFILE, MemoryRawStore(), HealthBook(), world.clock())
    ids = [e["id"] for e in rep.entries]
    assert len(ids) == len(set(ids)) and all(ids)


def test_a_duplicate_id_is_held_not_shipped():
    from mbos_discovery.recalls import RecallsReport, enforce_unique_ids
    e = {"id": "x", "source": {"title": "t"}, "evidence": {"provenance_id": "prov_" + "0" * 26}}
    rep = RecallsReport(entries=[e, dict(e, source={"title": "t2"})])
    enforce_unique_ids(rep)
    assert len(rep.entries) == 1 and rep.review[0]["candidate_entry"]["source"]["title"] == "t2"
    assert "duplicate KB entry id" in rep.review[0]["reason"]
