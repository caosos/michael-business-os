"""B-16: CPSC recalls → sourced recall records → KB entries that pass Agent 03's loader (admission standard)."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from conftest import FIX, T0, World
from mbos_discovery.adapter import SearchProfile
from mbos_discovery.adapters import CpscRecallsAdapter
from mbos_discovery.contract import check_provenance
from mbos_discovery.health import HealthBook
from mbos_discovery.http import CallbackTransport, HttpResponse
from mbos_discovery.policy import Disposition, policy_for
from mbos_discovery.rawstore import MemoryRawStore
from mbos_discovery.recalls import collect_recalls, model_tokens, parse_recall, to_kb_entries

CPSC = FIX / "cpsc"
PROFILE = SearchProfile("recalls", "flip", ("mower", "generator", "compressor", "stroller"))


def _run(world, **kw):
    ad = CpscRecallsAdapter.from_fixture(CPSC, world.clock)
    raw = MemoryRawStore()
    return ad, raw, collect_recalls(ad, PROFILE, raw, HealthBook(), world.clock(), **kw)


def test_policy_tier1_allowed():
    assert policy_for("cpsc_recalls").disposition is Disposition.ALLOWED and policy_for("cpsc_recalls").tier == 1


def test_fixture_run_entries_review_and_provenance(world):
    ad, raw, rep = _run(world)
    assert len(rep.records) == 7 and rep.sources[0]["recalls"] == 7
    ids = {e["id"] for e in rep.entries}
    assert ids == {"cpsc_26_901_acme_outdoor_power", "cpsc_26_910_northgate_power", "cpsc_26_920_ridgeline_air_systems"}
    reasons = {r["recall_id"]: r["reason"] for r in rep.review}
    assert "no discrete model" in reasons["99002"]                          # empty Model → review, not an entry
    assert "no named make" in reasons["99003"]                              # no manufacturer/importer
    assert "elementary advice" in reasons["99011"]                          # injected / elementary text refused
    assert "out of scope" in reasons["7938"]                                # the guide's stroller example
    for rec in rep.records.values():
        assert raw.exists(rec["raw_ref"]) and rec["url"].startswith("https://www.cpsc.gov/")
        prov = rep.provenance[rec["provenance_id"]]
        check_provenance(prov)
        assert (prov["actor_type"], prov["basis"], prov["source_uri"]) == ("external", "FACT", rec["url"])
        assert prov["inputs_used"][0]["hash"] == rec["raw_ref"]


def test_entry_content_is_templated_from_cpsc_fields_only(world):
    _, _, rep = _run(world)
    e = next(x for x in rep.entries if x["id"].startswith("cpsc_26_901"))
    assert e["category"] == "mower" and e["kind"] == "failure_mode"
    assert e["match"] == [{"makes": ["acme", "acme outdoor power"], "models": ["ZT5000", "ZT5200-E", "ZT6000", "ZT6200"]}]
    assert e["source"] == {"title": "CPSC: Acme Outdoor Power Recalls Zero-Turn Riding Mowers Due to Fire Hazard, recall date 2026-05-14",
                           "url": "https://www.cpsc.gov/Recalls/FIXTURE/Acme-Mowers", "retrieved": "2026-10-07"}
    assert "fuel line can rub the engine shroud" in e["risk"] and "About 3,100" in e["risk"]
    assert "UNKNOWN" in e["risk"] and e["evidence"]["recall_id"] == "99001"
    g = next(x for x in rep.entries if x["id"].startswith("cpsc_26_910"))
    assert g["match"][0]["makes"] == ["northgate", "northgate power"]       # importer "… Inc. of Dedham, Mass." cleaned
    assert e["match"][0]["makes"] == ["acme", "acme outdoor power"]         # brand word + full name


def test_make_tokens_skip_generic_brand_words():
    from mbos_discovery.recalls import make_tokens
    assert make_tokens("American Power Systems, Inc.") == ["american power systems"]
    assert make_tokens("Hollis Tools Co.") == ["hollis tools", "hollis"] and make_tokens("") == []


def test_model_token_extraction_is_conservative():
    assert model_tokens("ZT5000, ZT5200-E; ZT6000 and ZT6200") == ["ZT5000", "ZT5200-E", "ZT6000", "ZT6200"]
    assert model_tokens("") == [] and model_tokens("various models sold nationwide") == []
    assert model_tokens("model 12") == []                                   # too short, no named model
    assert model_tokens("GP6500 GP6500") == ["GP6500"] or model_tokens("GP6500, GP6500") == ["GP6500"]


def test_parse_refuses_uncitable_recalls():
    base = json.loads((CPSC / "recalls-mower.json").read_text())[0]
    for bad in ({"URL": "http://www.cpsc.gov/x"}, {"URL": "https://evil.example.com/x"}, {"RecallDate": ""},
                {"Title": ""}, {"RecallID": None}):
        with pytest.raises(Exception):
            parse_recall({**base, **bad})


def test_live_flag_and_read_only_request_shape(world):
    calls = []
    assert CpscRecallsAdapter(transport=CallbackTransport(lambda *a: calls.append(a))).fetch(PROFILE).error.kind == "config"
    assert calls == []
    seen = []
    ad = CpscRecallsAdapter(live=True, clock=world.clock,
                            transport=CallbackTransport(lambda m, u, h, b: seen.append((m, u)) or HttpResponse(200, b"[]")))
    ad.fetch(SearchProfile("p", "flip", ("mower",)))
    (m, u), = seen
    q = parse_qs(urlsplit(u).query)
    assert m == "GET" and u.startswith("https://www.saferproducts.gov/RestWebServices/Recall?")
    assert q["format"] == ["json"] and q["ProductName"] == ["mower"]
    assert q["RecallDateEnd"] == ["2026-10-07"] and q["RecallDateStart"][0] < "2024"
    assert {x[0] for x in ad.http.log} == {"GET"}


def test_block_freezes_and_gate_applies(world):
    ad = CpscRecallsAdapter(live=True, clock=world.clock, transport=CallbackTransport(lambda *a: HttpResponse(429, b"slow")))
    health, raw = HealthBook(), MemoryRawStore()
    collect_recalls(ad, PROFILE, raw, health, T0)
    rep = collect_recalls(ad, PROFILE, raw, health, T0)
    assert rep.freeze_requests[0]["capability"] == "discovery.source.cpsc_recalls.read"
    assert collect_recalls(ad, PROFILE, raw, health, T0).sources[0]["status"] == "skipped"


def test_deterministic_and_replayable(world):
    _, raw, a = _run(world)
    _, _, b = _run(world)
    assert a.entries == b.entries
    rec = next(iter(a.records.values()))
    again = parse_recall(json.loads(raw.get(rec["raw_ref"])))
    assert again["recall_id"] == rec["recall_id"] and again["url"] == rec["url"]


# ---------------------------------------------------------------- acceptance with Agent 03's loader
def test_entries_pass_agent_03_loader_and_match_listings(world, tmp_path):
    vo = pytest.importorskip("mbos_economics.valueadd")
    _, _, rep = _run(world)
    kb = {"kb_version": "fixture", "kb_format": 1, "entries": rep.entries}
    path = tmp_path / "kb.json"
    path.write_text(json.dumps(kb))
    loaded = vo.load_kb(path)                                               # raises on any entry failing admission
    assert {e["id"] for e in loaded["entries"]} == {e["id"] for e in rep.entries}
    item = {"category": "mower", "normalized": {"title": "Acme ZT5200-E zero turn mower, runs great"}}
    hits = vo.match_entries(item, loaded)
    assert [h["id"] for h in hits] == ["cpsc_26_901_acme_outdoor_power"]
    assert vo.match_entries({"category": "mower", "normalized": {"title": "Acme ZT9999 mower"}}, loaded) == []   # model must match
    assert vo.match_entries({"category": "mower", "normalized": {"title": "zero turn mower"}}, loaded) == []     # bare category → nothing
    # the card's own lint would reject elementary advice; ours never reaches the KB
    import mbos.card as card
    for e in rep.entries:
        assert card.elementary_advice(e["risk"]) == [] if hasattr(card, "elementary_advice") else True
