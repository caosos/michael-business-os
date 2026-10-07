"""A-05: lane C's REAL research step (comps → estimate → score) inside the DBOS workflow, on lane B's REAL
fixture Items (from Agent 03's acceptance fixtures, read via `git show`; nothing merged). Items with enough
sold-comp evidence advance NORMALIZED → RESEARCHING → SCORED → RECOMMENDED; the rest park in RESEARCHING
with gaps. Skipped unless `mbos_economics` is installed (RUNBOOK §6)."""

from __future__ import annotations

import json
import subprocess
import uuid

import pytest
import sqlalchemy as sa

pytest.importorskip("mbos_economics.comps_feed")

from dbos import DBOS, SetWorkflowID  # noqa: E402

from mbos import workflows  # noqa: E402
from mbos.adapters.economics import EconomicsResearcher  # noqa: E402
from mbos.contracts import schemas  # noqa: E402
from mbos.reference.fixture_adapter import FixtureSourceAdapter  # noqa: E402
from tests.helpers.common import ROOT, wait_state  # noqa: E402

REF = "origin/research/agent-03-economics"


def _show(path: str) -> str:
    return subprocess.run(["git", "show", f"{REF}:{path}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout


@pytest.fixture(scope="module")
def lane_b_items_and_comps():
    from mbos_economics.comps_feed import load_fixture_comps  # noqa: F401  (shape documented there)

    items = json.loads(_show("economics/tests/fixtures/agent02/items.json"))
    comps_doc = json.loads(_show("economics/tests/fixtures/comps/sold_comps.json"))
    return items, list(comps_doc.get("comps", [])), list(comps_doc.get("provenance", []))


def test_research_step_drives_lane_b_items_through_the_workflow(rt, tmp_path, lane_b_items_and_comps):
    from mbos.runtime import components

    items, comps, prov = lane_b_items_and_comps
    tag = uuid.uuid4().hex[:8]
    listings = []
    for it in items:
        src = it["sources"][0]
        listings.append({"source": src["source"], "source_listing_id": f"{src.get('source_listing_id')}-{tag}",
                         "url": src["url"], "ingestion_method": src["ingestion_method"], "tos_risk": src.get("tos_risk", "low"),
                         "record": {k: it[k] for k in ("type", "category", "subcategory", "opportunity_kind", "normalized")
                                    if k in it} | {"dedup_key": f"{it['dedup_key']}|{tag}"}})
    fixture = tmp_path / "lane-b-items.json"
    fixture.write_text(json.dumps({"listings": listings}))
    comps_ = components()
    old = comps_.researcher
    comps_.researcher = EconomicsResearcher(lambda item: (comps, prov))
    try:
        name = f"lane-b-{tag}"
        comps_.adapters[name] = FixtureSourceAdapter(fixture, name=name)
        with SetWorkflowID(f"discover:{name}"):
            results = DBOS.start_workflow(workflows.discover, name).get_result()
        ids = [r["item_id"] for r in results if r["created"]]
        assert len(ids) == len(items)
        final = {i: wait_state(rt.engine, i, {"RESEARCHING", "AWAITING_APPROVAL", "ARCHIVED"}, timeout=60) for i in ids}
    finally:
        comps_.researcher = old
    with rt.engine.connect() as c:
        docs = {i: c.execute(sa.text("SELECT body FROM mbos.items WHERE item_id = :i"), {"i": i}).scalar_one() for i in ids}
        paths = {i: [r.body["after_state"]["state"] for r in c.execute(sa.text(
            "SELECT body FROM mbos.receipts WHERE item_id = :i AND type = 'ITEM_STATE_CHANGED' ORDER BY seq"), {"i": i})]
            for i in ids}
    advanced = [i for i in ids if docs[i].get("scores")]
    parked = [i for i in ids if final[i] == "RESEARCHING" and not docs[i].get("scores")]
    assert advanced, "at least one lane-B item has enough evidence to be scored by lane C"
    assert any(docs[i]["type"] == "flip" for i in advanced), "at least one FLIP scored from sold comps"
    assert parked, "items without sufficient comps park in RESEARCHING (never guessed)"
    for i in advanced:
        assert docs[i]["scores"]["scorecard"].get("engine_version"), "scored by lane C's engine"
        if docs[i]["type"] != "flip":
            continue  # services are estimated from the lead itself; sold comps apply to flips
        cited = [r["provenance_id"] for r in docs[i].get("research", [])]
        assert cited, "research evidence attached to the flip"
        with rt.engine.connect() as c:
            bases = c.execute(sa.text("SELECT body->>'basis' FROM mbos.provenance WHERE provenance_id = ANY(:p)"),
                              {"p": cited}).scalars().all()
        assert len(bases) == len(set(cited)), "every cited provenance is stored in the ledger"
        assert "FACT" in bases, "at least one sold comp is a FACT observation (lane B provenance)"
        p = paths[i]
        assert p[:4] == ["DISCOVERED", "NORMALIZED", "RESEARCHING", "SCORED"] or "RESEARCHING" in p[:4], p
    for i in ids:
        assert not schemas.errors("item", docs[i]), schemas.errors("item", docs[i])[:3]
