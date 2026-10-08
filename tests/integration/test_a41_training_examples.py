"""A-41: the ILLUSTRATIVE training set (fixtures/sources/training_examples.json) through the REAL assembly on lane D / PG16 with a $500 bankroll:
a YES awaiting approval, a MAYBE that names its missing evidence, a PASS with the bankroll reason, and a service lead that moves once Michael
attests the evidence lane C asked for. Own process (DBOS is a per-process singleton)."""

from __future__ import annotations

import io
import json
import subprocess
import tarfile

import pytest

from mbos import card as cardmod
from tests.helpers import lane_d
from tests.helpers.common import ROOT
from tests.helpers.proc import line, run_runner

FIXTURE = ROOT / "fixtures" / "sources" / "training_examples.json"


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    pgserver = pytest.importorskip("pgserver")
    pytest.importorskip("mbos_governance")
    pytest.importorskip("mbos_economics")
    tmp = tmp_path_factory.mktemp("a41")
    src = tmp / "src"
    src.mkdir()
    lane_d.extract(src)
    tar = subprocess.run(["git", "archive", "origin/research/agent-05-governance", "policy"], cwd=ROOT, capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(tmp, filter="data")
    server = pgserver.get_server(str(tmp / "pg"), cleanup_mode="stop")
    try:
        app, sysu, owner = lane_d.build_as_worker(server, src, "mbos_a41")
        cp = run_runner((app, sysu), "training_set", str(FIXTURE), timeout=240, extra_env={
            "MBOS_OWNER_DATABASE_URL": owner, "PYTHONPATH": str(ROOT / "src"), "MBOS_SCORER": "engine", "MBOS_POLICY_PATH": str(tmp / "policy" / "policy.v1.json"),
            "MBOS_EGRESS_FILE": str(tmp / "egress.json"), "MBOS_LITELLM_FILE": str(tmp / "litellm.json")})
        assert cp.returncode == 0, cp.stdout[-3000:] + cp.stderr[-14000:]
        yield json.loads(line(cp, "RESULT"))
    finally:
        server.cleanup()


def test_fixture_is_labelled_illustrative_and_every_assumption_has_a_basis():
    doc = json.loads(FIXTURE.read_text())
    assert "ILLUSTRATIVE" in doc["_comment"]
    for l in doc["listings"]:
        assert l["url"].startswith("https://example.invalid/")
        econ = l["record"]["economics"]
        for a in econ["estimates_meta"].get("assumptions", []):
            assert a["basis"] in ("FACT", "INFER", "REC", "UNK") and a["note"], a


def test_a_yes_awaits_approval_within_the_bankroll(result):
    tv = result["first"]["TRAIN-TV-1"]
    assert (tv["state"], tv["verdict"]) == ("AWAITING_APPROVAL", "YES"), tv["rationale"]
    assert tv["card"]["recommendation"]["action"] == "CONTACT"
    assert result["capital"]["available_to_deploy"] == 500


def test_a_maybe_names_its_missing_evidence(result):
    recon = result["first"]["TRAIN-RECON-1"]
    assert (recon["state"], recon["verdict"]) == ("RESEARCHING", "MAYBE")
    assert "fault_identified" in recon["cheapest"] and any("fault not identified" in r for r in recon["rationale"]), recon["rationale"]


def test_a_pass_gives_the_bankroll_reason(result):
    mower = result["first"]["TRAIN-MOWER-1"]
    assert (mower["state"], mower["verdict"]) == ("ARCHIVED", "PASS")
    assert any("cash tied up" in r and "can fund" in r for r in mower["rationale"]), mower["rationale"]
    assert mower["pass_on_priors"] is False                       # the buy price and parts are FACT: an evidence-backed PASS


def test_the_service_lead_waits_for_attestation_then_moves(result):
    lead = result["first"]["TRAIN-LEAD-DRYWALL-1"]
    assert (lead["state"], lead["verdict"]) == ("RESEARCHING", "MAYBE")
    assert "scope_verified" in lead["cheapest"] and "customer_screened" in lead["cheapest"]
    after = result["lead_after"]
    assert (after["state"], after["verdict"]) == ("AWAITING_APPROVAL", "YES"), after["rationale"]


def test_every_card_validates_and_every_number_is_labelled(result):
    def walk(node, path, bad):
        if isinstance(node, dict):
            if "value" in node and "basis" in node and node["basis"] not in ("FACT", "INFERENCE", "RECOMMENDATION", "UNKNOWN"):
                bad.append(path)
            for k, v in node.items():
                walk(v, f"{path}.{k}", bad)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]", bad)

    for name, snap in [*result["first"].items(), ("lead_after", result["lead_after"])]:
        assert snap["card_errors"] == [], (name, snap["card_errors"])
        assert not cardmod.validate_card(snap["card"])
        bad: list = []
        walk(snap["card"], name, bad)
        assert not bad, bad
