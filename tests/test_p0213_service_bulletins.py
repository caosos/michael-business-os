"""P-02-13: NHTSA service-bulletin file → KB entries (R23 admission) that Agent 03's load_kb accepts."""

import json

import pytest

import mbos_discovery.service_bulletins as sb
from conftest import FIX, T0
from mbos_discovery.contract import check_provenance
from mbos_discovery.rawstore import MemoryRawStore

FILE = FIX / "nhtsa_tsb" / "tsbs-fixture.txt"


@pytest.fixture
def rep():
    return sb.collect_bulletins(FILE, MemoryRawStore(), T0)


def test_only_complete_rows_are_admitted(rep):
    assert {e["id"] for e in rep.entries} == {"nhtsa_tsb_10000001_fixmotors_roadster", "nhtsa_tsb_10000002_fixmotors_roadster"}
    held = {r["recall_id"]: r["reason"] for r in rep.review}
    assert set(held) == {"10000003", "10000004", "10000005", "10000006", "10000007", "10000008"}
    assert "no summary" in held["10000003"] and "all-years" in held["10000004"] and "numeric" in held["10000005"]
    assert "instruction-like" in held["10000006"] and "elementary-advice" in held["10000007"] and "date" in held["10000008"]
    assert rep.sources[0]["rows"] == 9 and rep.sources[0]["entries"] == 2 and rep.sources[0]["review"] == 6


def test_years_grouped_and_wording_is_not_a_defect_claim(rep):
    e = next(x for x in rep.entries if x["id"].endswith("10000001_fixmotors_roadster"))
    assert e["match"] == [{"makes": ["fixmotors"], "models": ["ROADSTER"], "years": [2012, 2013]}]
    assert "not a recall" in e["risk"] and "UNKNOWN" in e["risk"]


def test_provenance_and_raw_retained():
    raw = MemoryRawStore()
    r = sb.collect_bulletins(FILE, raw, T0)
    for e in r.entries:
        p = r.provenance[e["evidence"]["provenance_id"]]
        check_provenance(p)
        assert (p["basis"], p["actor_type"]) == ("FACT", "external") and raw.exists(e["evidence"]["raw_ref"])
        assert p["inputs_used"][0]["hash"] == e["evidence"]["raw_ref"]


def test_injected_text_never_reaches_an_entry(rep):
    assert "approve" not in json.dumps(rep.entries).lower()
    assert next(r for r in rep.review if r["recall_id"] == "10000006").get("candidate_entry") is None


def test_wrong_layout_is_quarantined(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("a\tb\n1\t2\n")
    r = sb.collect_bulletins(f, MemoryRawStore(), T0)
    assert r.entries == [] and r.sources[0]["status"] == "error" and r.quarantine


def test_load_kb_accepts_and_matches(rep, tmp_path):
    vo = pytest.importorskip("mbos_economics.valueadd")
    p = tmp_path / "kb.json"
    p.write_text(json.dumps({"kb_version": "fixture", "kb_format": 1, "entries": rep.entries}))
    kb = vo.load_kb(p)
    assert {e["id"] for e in kb["entries"]} == {e["id"] for e in rep.entries}
    hits, _ = vo.match_hits({"category": "project_vehicle", "normalized": {"title": "2013 Fixmotors Roadster"}}, kb)
    assert "nhtsa_tsb_10000001_fixmotors_roadster" in {h["entry"]["id"] for h in hits}
    hits, blocked = vo.match_hits({"category": "project_vehicle", "normalized": {"title": "2018 Fixmotors Roadster"}}, kb)
    assert hits == [] and blocked
