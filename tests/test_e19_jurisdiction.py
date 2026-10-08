"""E-19: jurisdiction packs + eligibility(job, packs). Pilot data is a synthetic sample:true fixture; no legal fact."""
from __future__ import annotations

import ast
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mbos_governance import jurisdiction as jx
from mbos_governance.ids import fmt_ts, new_id

REPO = Path(__file__).resolve().parents[1]
DATA = jx.JurisdictionData(REPO / "policy" / "jurisdiction")
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
ST, CO = "SAMPLE-ST", "SAMPLE-ST/SAMPLE-COUNTY-A"
CITY, UNIN = f"{CO}/SAMPLE-CITY-1", f"{CO}/UNINCORPORATED"
IN_CITY, IN_UNIN = [ST, CO, CITY], [ST, CO, UNIN]


def job(jc, chain=IN_CITY, **kw):
    return {"job_class": jc, "jurisdiction_chain": chain, **kw}


def ev(j, packs=None, now=NOW):
    return jx.eligibility(j, DATA.packs if packs is None else packs, DATA, now)


def pack(**over):
    p = {"pack_id": "t-" + new_id("p")[-6:].lower(), "jurisdiction": CITY, "job_class": "tile_work", "rule": "SAMPLE RULE", "source": "SYNTHETIC-FIXTURE",
         "date_verified": "2026-09-01", "credential_required": ["residential_license_verified"], "permit_notes": "", "confidence": 0.9,
         "unresolved": [], "sample": True}
    p.update(over)
    return p


def claim(cred="electrical_license_verified", jurisdiction=ST, **over):
    c = {"claim_id": new_id("clm"), "subject": "provider:p1", "credential": cred, "status": "verified",
         "evidence": [{"kind": "regulator_lookup_result", "ref": "lookup:1"}], "verifier": {"type": "regulator_lookup", "id": "lookup:sample"},
         "verified_at": "2026-09-01T00:00:00Z", "expires_at": "2027-09-01T00:00:00Z", "jurisdiction": jurisdiction,
         "provenance_ids": [new_id("prov")]}
    c.update(over)
    return c


# ---------------------------------------------------------------- the shipped data
def test_shipped_pilot_data_is_valid_synthetic_and_asserts_no_legal_fact():
    assert jx.data_problems(DATA, NOW.date()) == []
    assert DATA.packs and all(p["sample"] is True and p["source"] == "SYNTHETIC-FIXTURE" and p["jurisdiction"].startswith("SAMPLE-")
                              for p in DATA.packs)
    notice = json.loads((REPO / "policy/jurisdiction/packs/sample-pilot.v1.json").read_text())["fixture_notice"]
    assert "SYNTHETIC" in notice and "No real jurisdiction" in notice


# ---------------------------------------------------------------- missing pack => UNKNOWN, never "no licence needed"
@pytest.mark.parametrize("j", [
    job("roofing"),                                              # no pack for the job class anywhere
    job("electrical_repair", ["OTHER-ST", "OTHER-ST/OTHER-COUNTY"]),    # a place no pack covers
    job("furniture_assembly", IN_UNIN),                          # only a CITY pack exists: nothing is inferred for the unincorporated area
    job("plumbing_repair", [ST]),                                # pack is county-level; a state-only chain does not reach it
])
def test_missing_pack_is_unknown_never_eligible(j):
    r = ev(j)
    assert r["status"] == "UNKNOWN" and any(x.startswith("NO_PACK") for x in r["reasons"])
    assert r["credential_required"] is None and r["authoritative"] is False
    assert jx.gate(r, DATA) == "ask_michael"
    assert "no licence needed" in " ".join(r["reasons"]) and r["status"] != "eligible"      # the reason says what it is NOT


def test_no_jurisdiction_or_a_bad_chain_is_unknown():
    for chain in (None, [], "SAMPLE-ST", [ST, "SAMPLE-ST-X/other"], [CITY, ST]):
        r = ev({"job_class": "electrical_repair", "jurisdiction_chain": chain})
        assert r["status"] == "UNKNOWN" and r["reasons"][0].startswith("NO_JURISDICTION"), chain
    assert ev({"jurisdiction_chain": IN_CITY})["status"] == "UNKNOWN"


# ---------------------------------------------------------------- the evaluator knows no local law
def test_evaluator_hard_codes_no_city_limit_assumption():
    tree = ast.parse((REPO / "src/mbos_governance/jurisdiction.py").read_text())
    docstrings = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
                  and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    consts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]
    banned = ("incorporated", "city limit", "county", "arkansas", "unincorporated")
    assert not [c for c in consts if any(b in c.lower() for b in banned) and "SAMPLE" not in c and not c.startswith(("NO_", "MISSING", "CONFLICT", "EXPIRED"))
                and "inferred" not in c], [c for c in consts if any(b in c.lower() for b in banned)]


def test_an_unknown_place_with_an_incorporated_flag_changes_nothing():
    base = ev(job("furniture_assembly", IN_UNIN))
    flagged = ev(job("furniture_assembly", IN_UNIN, incorporated=False, outside_city_limits=True))
    assert base["status"] == flagged["status"] == "UNKNOWN"


# ---------------------------------------------------------------- cited results
def test_needs_credential_cites_the_rule():
    r = ev(job("electrical_repair"))
    assert r["status"] == "needs_credential" and r["credential_required"] == ["electrical_license_verified"]
    assert r["missing_credentials"] == ["electrical_license_verified"]
    c = r["cited"]
    assert c["pack_id"] == "sample-st-electrical" and c["source"] == "SYNTHETIC-FIXTURE" and c["date_verified"] == "2026-08-01"
    assert "electrical" in c["rule"] and r["confidence"] == 0.9 and r["authoritative"] is False and r["sample"] is True
    assert jx.gate(r, DATA) == "ask_michael"                 # a fixture can never unblock anything


def test_provider_holding_the_credential_is_eligible_only_with_a_valid_claim_in_the_jurisdiction():
    good = ev(job("electrical_repair", provider_claims=[claim()]))
    assert good["status"] == "eligible" and good["missing_credentials"] == []
    bad = {
        "wrong place": claim(jurisdiction="OTHER-ST"),
        "expired": claim(expires_at="2026-01-01T00:00:00Z"),
        "not verified": claim(status="pending"),
        "wrong credential": claim("plumbing_license_verified"),
        "no evidence": claim(evidence=[]),
        "bare word": claim("verified"),
    }
    for why, c in bad.items():
        r = ev(job("electrical_repair", provider_claims=[c]))
        assert r["status"] == "needs_credential", why
    r = ev(job("electrical_repair", provider_claims=[claim(jurisdiction="OTHER-ST")]))
    assert any("not in this job's jurisdiction" in x for x in r["reasons"])


def test_most_specific_pack_wins():
    packs = [pack(jurisdiction=ST, credential_required=["residential_license_verified"]),
             pack(jurisdiction=CITY, credential_required=[])]
    assert ev(job("tile_work"), packs)["credential_required"] == []
    assert ev(job("tile_work", [ST, CO]), packs)["credential_required"] == ["residential_license_verified"]


def test_conflicting_packs_at_the_same_level_are_unknown():
    packs = [pack(credential_required=["residential_license_verified"]), pack(credential_required=[])]
    r = ev(job("tile_work"), packs)
    assert r["status"] == "UNKNOWN" and r["reasons"][0].startswith("CONFLICT")


# ---------------------------------------------------------------- thresholds
def test_threshold_packs():
    small = ev(job("drywall_repair", scope={"value_usd": 400}))
    assert small["status"] == "eligible" and small["credential_required"] == [] and small["cited"]["pack_id"] == "sample-city1-drywall"
    big = ev(job("drywall_repair", scope={"value_usd": 1000}))
    assert big["status"] == "needs_credential" and big["credential_required"] == ["residential_license_verified"]
    missing = ev(job("drywall_repair"))
    assert missing["status"] == "UNKNOWN" and missing["reasons"][-1].startswith("MISSING_JOB_FIELD")


def test_a_threshold_that_matches_no_pack_is_unknown():
    packs = [pack(threshold={"field": "value_usd", "op": "gte", "value": 5000}, credential_required=["residential_license_verified"])]
    assert ev(job("tile_work", scope={"value_usd": 100}), packs)["status"] == "UNKNOWN"


# ---------------------------------------------------------------- staleness lowers confidence
@pytest.mark.parametrize("date_verified,expected", [("2026-09-01", 0.9), ("2026-02-01", 0.63), ("2025-06-01", 0.36)])
def test_stale_date_verified_lowers_confidence(date_verified, expected):
    r = ev(job("tile_work"), [pack(date_verified=date_verified)])
    assert r["status"] == "needs_credential" and r["confidence"] == pytest.approx(expected)
    assert (expected < 0.9) == any(x.startswith("STALE") for x in r["reasons"])


def test_a_very_old_pack_is_expired_and_unknown():
    r = ev(job("tile_work"), [pack(date_verified="2024-01-01")])
    assert r["status"] == "UNKNOWN" and r["reasons"][0].startswith("EXPIRED_PACK") and r["authoritative"] is False


def test_the_shipped_old_hvac_sample_shows_staleness():
    r = ev(job("hvac_service", [ST]))
    assert r["status"] == "needs_credential" and r["confidence"] == pytest.approx(0.36)
    later = ev(job("hvac_service", [ST]), now=datetime(2027, 12, 1, tzinfo=timezone.utc))
    assert later["status"] == "UNKNOWN"


# ---------------------------------------------------------------- uncertainty never removes a requirement
def test_uncertainty_keeps_a_requirement_but_cannot_clear_one():
    low_requires = ev(job("tile_work"), [pack(confidence=0.3)])
    assert low_requires["status"] == "needs_credential" and low_requires["confidence"] == 0.3
    low_clears = ev(job("tile_work"), [pack(credential_required=[], confidence=0.5)])
    assert low_clears["status"] == "UNKNOWN" and low_clears["reasons"][-1].startswith("UNCERTAIN")
    stale_clears = ev(job("tile_work"), [pack(credential_required=[], date_verified="2025-06-01")])
    assert stale_clears["status"] == "UNKNOWN"                       # 0.9 x 0.4 < 0.7: a stale 'no credential' finding cannot clear
    fresh_clears = ev(job("tile_work"), [pack(credential_required=[], confidence=0.9)])
    assert fresh_clears["status"] == "eligible" and fresh_clears["credential_required"] == []


def test_unresolved_questions_and_null_requirements():
    unresolved = ev(job("smart_home_install"))
    assert unresolved["status"] == "UNKNOWN" and unresolved["reasons"][-1].startswith("UNRESOLVED")
    plumbing = ev(job("plumbing_repair", [ST, CO]))
    assert plumbing["status"] == "needs_credential" and plumbing["unresolved"] == ["Does the county require a separate permit for fixture swaps?"]


# ---------------------------------------------------------------- pack validation
@pytest.mark.parametrize("over,needle", [
    ({"credential_required": ["verified"]}, "BARE_VERIFIED"),
    ({"credential_required": ["notary_verified"]}, "not in the E-18 vocabulary"),
    ({"date_verified": "2999-01-01"}, "future"),
    ({"credential_required": [], "unresolved": ["open?"]}, "cannot affirm"),
    ({"source": "https://example.test/rule"}, "sample pack must use"),
    ({"confidence": 2}, "schema"),
    ({"job_class": "Bad Class"}, "schema"),
    ({"extra": 1}, "schema"),
])
def test_invalid_packs(over, needle):
    probs = jx.pack_problems(pack(**over), DATA, NOW.date())
    assert any(needle in x for x in probs), probs
    assert ev(job("tile_work"), [pack(**over)])["status"] == "UNKNOWN"          # an invalid pack is ignored, never trusted


def test_real_packs_need_a_citation_and_a_verifier():
    real = pack(sample=False, jurisdiction="REAL-PLACE", source="my notes")
    probs = jx.pack_problems(real, DATA, NOW.date())
    assert any("cite a URL" in x for x in probs) and any("verified_by" in x for x in probs)
    ok = pack(sample=False, jurisdiction="REAL-PLACE", source="https://example.test/ordinance", verified_by="human:reviewer")
    assert jx.pack_problems(ok, DATA, NOW.date()) == []
    r = ev(job("tile_work", ["REAL-PLACE"]), [ok])
    assert r["status"] == "needs_credential" and r["authoritative"] is True and jx.gate(r, DATA) == "block_until_credential"
    cleared = ev(job("tile_work", ["REAL-PLACE"]), [{**ok, "credential_required": [], "date_verified": "2026-09-30"}])
    assert cleared["status"] == "eligible" and jx.gate(cleared, DATA) == "allow"


def test_cli(capsys, tmp_path):
    from mbos_governance.cli import main
    pol = str(REPO / "policy/policy.v1.json")
    assert main(["--policy", pol, "jurisdiction", "check"]) == 0
    jf = tmp_path / "job.json"
    jf.write_text(json.dumps(job("electrical_repair")))
    capsys.readouterr()
    assert main(["--policy", pol, "jurisdiction", "eligibility", "--job", str(jf)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "needs_credential" and out["gate"] == "ask_michael"
    jf.write_text(json.dumps(job("roofing")))
    assert main(["--policy", pol, "jurisdiction", "eligibility", "--job", str(jf)]) == 3         # UNKNOWN => exit 3
