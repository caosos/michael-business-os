"""End-to-end fixture runner: one flip + one service through the whole dry-run spine."""
from __future__ import annotations

import json
import pathlib

from . import drafts
from .core import parse_duration

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures"
DRAFTERS = {"seller_inquiry": drafts.seller_inquiry, "resale_listing": drafts.resale_listing,
            "service_quote": drafts.service_quote}


def _load(d: pathlib.Path, name: str):
    return json.loads((d / name).read_text())


def run_fixture(h, fixture_dir: pathlib.Path) -> dict:
    wf = h.workflow
    raw = _load(fixture_dir, "raw.json")
    plan = _load(fixture_dir, "plan.json")
    item_id = wf.ingest(fixture_dir / "raw.json")
    if "attribution" in raw:
        wf.record_attribution(item_id, raw["attribution"])
    wf.research(item_id, _load(fixture_dir, "research.json"))
    wf.score(item_id, _load(fixture_dir, "economics.json"), skills_on_file=set(plan["skills_on_file"]),
             scarcity=plan["scarcity"])
    item = h.store.get("item", item_id)

    proposals, params_by_index = [], []
    for a in plan["actions"]:
        payload = DRAFTERS[a["draft"]](item, **a["params"])
        proposals.append({**{k: v for k, v in a.items() if k not in ("draft", "params")}, "payload": payload})
        params_by_index.append((a["draft"], dict(a["params"])))
    verdict = wf.recommend(item_id, proposals)

    if verdict == "YES":
        reqs = h.store.action_requests(item_id=item_id)
        for d in plan["decisions"]:
            areq = reqs[d["action"]]
            draft_name, params = params_by_index[d["action"]]
            steps = [(d["decision"], d)]
            if d.get("then"):
                steps.append((d["then"], d))
            if d.get("finally"):
                steps.append((d["finally"], d))
            current = areq["action_request_id"]
            for i, (decision, spec) in enumerate(steps):
                if decision == "HOLD":
                    wf.decide(current, "HOLD", hold=spec["hold"])
                    if spec.get("advance"):
                        h.clock.advance(parse_duration(spec["advance"]))
                        wf.tick()
                elif decision == "MODIFY":
                    params = {**params, **spec["modify"]}
                    new_payload = DRAFTERS[draft_name](h.store.get("item", item_id), **params)
                    appr = wf.decide(current, "MODIFY", new_payload=new_payload)
                    current = appr["modifications"]["new_action_request_id"]
                elif decision == "NO":
                    wf.decide(current, "NO", reason=spec.get("reason", "fixture"))
                else:
                    wf.decide(current, decision)
        wf.act(item_id)
    return {"item_id": item_id, "fixture": fixture_dir.name, "verdict": verdict}


def run_all(h, fixtures_root: pathlib.Path = FIXTURES) -> list[dict]:
    return [run_fixture(h, d) for d in sorted(p for p in fixtures_root.iterdir() if p.is_dir())]
