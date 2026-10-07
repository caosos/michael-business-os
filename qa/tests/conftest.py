"""Shared fixtures. Every test builds its harness through `mbos_qa.harness.build`, so the same suite runs
against the reference mocks today and against real lanes when MBOS_QA_IMPL points at them."""
from __future__ import annotations

import json
import pathlib

import pytest

from mbos_qa import drafts
from mbos_qa.e2e import FIXTURES, run_all
from mbos_qa.harness import build


@pytest.fixture
def h(tmp_path):
    return build(tmp_path / "run")


@pytest.fixture
def ran(tmp_path):
    """Harness after both end-to-end fixtures have run to completion (dry-run)."""
    hh = build(tmp_path / "run")
    hh.results = run_all(hh)
    return hh


def pending(h, fixture: str = "flip_trailer", action_index: int = 0, listing: str | None = None,
            **overrides) -> tuple[str, dict]:
    """Bring one fixture item to AWAITING_APPROVAL with exactly one ActionRequest; return (item_id, areq).
    `listing` clones the fixture as a distinct source listing (so one harness can hold several items)."""
    d = FIXTURES / fixture
    plan = json.loads((d / "plan.json").read_text())
    wf = h.workflow
    raw_path = d / "raw.json"
    if listing:
        raw = json.loads(raw_path.read_text())
        raw["source_listing_id"] = f"{raw.get('source_listing_id', 'QA')}-{listing}"
        raw["url"] += f"-{listing}"
        raw_path = h.workdir / f"raw-{fixture}-{listing}.json"
        raw_path.write_text(json.dumps(raw))
    item_id = wf.ingest(raw_path)
    wf.research(item_id, json.loads((d / "research.json").read_text()))
    wf.score(item_id, json.loads((d / "economics.json").read_text()), skills_on_file=set(plan["skills_on_file"]),
             scarcity=plan["scarcity"])
    a = dict(plan["actions"][action_index])
    payload = getattr(drafts, a.pop("draft"))(h.store.get("item", item_id), **a.pop("params"))
    a.update(overrides)
    assert wf.recommend(item_id, [{**a, "payload": payload}]) == "YES"
    (areq,) = h.store.action_requests(item_id=item_id)
    return item_id, areq


def approve(h, areq: dict, **kw) -> dict:
    return h.workflow.decide(areq["action_request_id"], "YES", **kw)


def effector_attempts(h) -> int:
    return sum(e.call_count() for e in h.effectors.values())


def receipts_of(h, type_: str, **where) -> list[dict]:
    return h.store.receipts(type=type_, **where)


ROOT = pathlib.Path(__file__).resolve().parent.parent
