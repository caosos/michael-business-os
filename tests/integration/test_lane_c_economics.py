"""Cross-lane: Agent 03's REAL economics engine behind the spine's Scorer, through the real DBOS workflow.

Skipped unless `mbos_economics` is installed (from Agent 03's branch; see src/mbos/adapters/economics.py).
The config is read from Agent 03's pinned commit with `git show`, never copied into this branch."""

import subprocess
import uuid

import pytest

pytest.importorskip("mbos_economics")

from mbos.adapters.economics import EconomicsEngineScorer  # noqa: E402
from mbos.contracts import schemas  # noqa: E402
from tests.helpers.common import ROOT, pending_request, scalar, wait_state  # noqa: E402

LANE_C_COMMIT = "dcd6883"


@pytest.fixture(scope="module")
def lane_c_config(tmp_path_factory):
    """Lane C's whole config dir at the pushed head: the installed engine must be paired with ITS config (the gate checks
    that the installed engine equals that head). Pinning an old config here broke when C-19 added class_gates."""
    import io
    import tarfile

    d = tmp_path_factory.mktemp("lane-c-config")
    tar = subprocess.run(["git", "archive", "origin/research/agent-03-economics", "economics/src/mbos_economics/config"], cwd=ROOT,
                         capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        for m in t.getmembers():
            if m.isfile():
                dest = d / m.name.removeprefix("economics/src/mbos_economics/config/")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(t.extractfile(m).read())
    return d


@pytest.fixture()
def real_scorer(rt, lane_c_config):
    from mbos.runtime import components

    old = components().scorer
    components().scorer = EconomicsEngineScorer(config_dir=lane_c_config)
    yield components().scorer
    components().scorer = old


def test_engine_output_is_a_valid_score_result_and_replays(real_scorer):
    import json
    item = json.loads((ROOT / "docs/research/contracts/examples/item-service-drywall.example.json").read_text())
    a, b = real_scorer.score(item), real_scorer.score(item)
    assert a == b, "deterministic replay"
    assert a.scorecard_id.startswith("scr_") and a.recommendation_id.startswith("rec_")
    assert not schemas.errors("scorecard", a.scorecard)
    assert a.verdict in ("YES", "MAYBE", "PASS")


def test_real_engine_drives_the_workflow(rt, run_discovery, real_scorer):
    ids = run_discovery("FIX-TRAILER-1", "FIX-LEAD-SMARTHOME-1", "FIX-MOWER-1", "FIX-LEAD-DRYWALL-1")
    final = {k: wait_state(rt.engine, v, {"AWAITING_APPROVAL", "RESEARCHING", "ARCHIVED"}) for k, v in ids.items()}
    assert final["FIX-MOWER-1"] in ("ARCHIVED", "RESEARCHING")  # PASS: archived, unless it rests on priors only (R13/A-12)
    with rt.engine.connect() as c:
        import sqlalchemy as sa
        for listing, item_id in ids.items():
            body = c.execute(sa.text("SELECT body FROM mbos.items WHERE item_id = :i"), {"i": item_id}).scalar_one()
            assert body["scores"]["scorecard"].get("engine_version"), "scored by lane C, not the placeholder"
            assert not schemas.errors("item", body)
            v = body["recommendation"]["verdict"]
            priors = body["scores"]["scorecard"].get("pass_on_priors") is True
            assert final[listing] == {"YES": "AWAITING_APPROVAL", "MAYBE": "RESEARCHING", "PASS": "RESEARCHING" if priors else "ARCHIVED"}[v]


def test_item_without_economics_parks_in_research(rt, run_discovery, real_scorer):
    item_id = run_discovery("FIX-TRAILER-1-DUP")["FIX-TRAILER-1-DUP"]  # no economics in this record
    assert wait_state(rt.engine, item_id, "RESEARCHING")
    assert "Economics inputs missing" in scalar(rt.engine, "SELECT body->'recommendation'->'rationale'->>0 FROM mbos.items WHERE item_id = :i", i=item_id)
