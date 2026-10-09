"""B-24: pivot classification (trailer subtype, donor RV, log splitter / towable, ATV; paperwork and condition as
quoted evidence only). Reuses the B-21 tagger; paperwork is never inferred without text."""

from __future__ import annotations

import json

import pytest

from conftest import FIX
from mbos_discovery.tags import build_category_tags

PROV = "prov_" + "0" * 26
CASES = json.loads((FIX / "pivot_listings.json").read_text())["cases"]


def _pivot(title, description=""):
    item = {"type": "flip", "opportunity_kind": "buy_item", "normalized": {"title": title, "description": description}}
    return build_category_tags(item, PROV).get("pivot", {"subtypes": [], "paperwork": [], "condition": []})


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_fixture_listings_tag_correctly(case):
    p = _pivot(case["title"], case["description"])
    for cat in ("subtypes", "paperwork", "condition"):
        got = {x["class"]: " | ".join(e["quote"] for e in x["evidence"]) for x in p[cat]}
        want = case["expect"][cat]
        assert set(got) == set(want), (cat, got, want)
        for cls, needles in want.items():
            assert all(n.lower() in got[cls].lower() for n in needles), (cls, got[cls])


def test_paperwork_never_inferred_without_text():
    for t in ("Utility trailer", "Camper for parts", "Boat trailer, ready to go", "ATV 2005, runs", "Trailer title"):
        assert _pivot(t, "Call for details.")["paperwork"] == [], t


def test_all_evidence_is_quoted_and_block_stays_additive():
    item = {"type": "flip", "opportunity_kind": "buy_item", "normalized": {"title": "Tandem axle utility trailer", "description": "Clean title"}}
    b = build_category_tags(item, PROV)
    assert b["evaluated"] and b["tags"] == []
    for cat in b["pivot"].values():
        for x in cat:
            assert x["evidence"] and all(e["quote"] and "field" in e for e in x["evidence"])
