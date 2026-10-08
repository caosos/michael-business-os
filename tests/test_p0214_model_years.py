"""P-02-14: shorthand model years (`'18`, `MY2018`) from real listing-title shapes, with negatives."""

import json

import pytest

import mbos_discovery.model_years as my

POS = [
    ("'18 Fixmotors Roadster low miles", [2018]),
    ("’18 Fixmotors Roadster", [2018]),            # typographic apostrophe
    ("Fixmotors Roadster '13 clean title", [2013]),
    ("MY2018 Fixmotors Roadster", [2018]),
    ("my 2018 Fixmotors Roadster", [2018]),
    ("Fixmotors Roadster MY18 manual", [2018]),
    ("Fixmotors Roadster MY-2018", [2018]),
    ("'98 Fixmotors Roadster", [1998]),
    ("'05 Fixmotors Roadster, MY2005", [2005]),
    ("'13 / MY2014 Fixmotors Roadster", [2013, 2014]),
]
NEG = [
    "Fixmotors Roadster 5'10 ladder",
    "Fixmotors Roadster 6'18\" pipe",
    "Fixmotors Roadster part # MY18-4420",
    "Fixmotors Roadster part MY2018A",
    "Fixmotors Roadster PN'18",
    "Fixmotors Roadster 18% off",
    "Fixmotors Roadster $'18",
    "Fixmotors Roadster '18.5 gauge",
    "Fixmotors Roadster 2018",                          # four-digit is Agent 03's job
    "Fixmotors Roadster MY1812",                        # outside the window
    "Fixmotors Roadster '47",                           # 1947: before 1950
    "Fixmotors Roadster '36 shelf",                     # 1936: before 1950
    "Fixmotors Roadster 18",
    "",
]


@pytest.mark.parametrize("title,years", POS)
def test_positive(title, years):
    got = my.extract_model_years(title)
    assert [r["year"] for r in got] == years
    assert all(r["basis"] == "INFERENCE" for r in got)


@pytest.mark.parametrize("title", NEG)
def test_negative_is_not_a_year(title):
    assert my.extract_model_years(title) == []


def test_for_kb_match_does_not_mutate_and_skips_stated_year():
    item = {"normalized": {"title": "'18 Fixmotors Roadster"}}
    aug, found = my.for_kb_match(item)
    assert item["normalized"]["title"] == "'18 Fixmotors Roadster" and aug["normalized"]["title"].endswith("2018")
    same, _ = my.for_kb_match({"normalized": {"title": "2018 Fixmotors Roadster MY2018"}})
    assert same["normalized"]["title"] == "2018 Fixmotors Roadster MY2018"
    plain = {"normalized": {"title": "Fixmotors Roadster"}}
    assert my.for_kb_match(plain) == (plain, [])


def test_card_line_is_inference_only():
    assert my.card_line([]) is None
    line = my.card_line(my.extract_model_years("MY2018 Fixmotors Roadster"))
    assert line.startswith("INFERENCE:") and "not confirmed" in line and "FACT" not in line


def _kb(tmp_path, years):
    vo = pytest.importorskip("mbos_economics.valueadd")
    e = {"id": "x_fix_roadster", "category": "project_vehicle", "match": [{"makes": ["fixmotors"], "models": ["roadster"], "years": years}],
         "kind": "known_weakness", "risk": "Manufacturer issued a bulletin for this model.",
         "source": {"title": "NHTSA bulletin 1", "url": "https://www.nhtsa.gov/", "retrieved": "2026-10-07"}}
    p = tmp_path / "kb.json"
    p.write_text(json.dumps({"kb_version": "fixture", "kb_format": 1, "entries": [e]}))
    return vo, vo.load_kb(p)


def test_matcher_hits_shorthand_year_only_through_the_helper(tmp_path):
    vo, kb = _kb(tmp_path, [2018])
    item = {"category": "project_vehicle", "normalized": {"title": "'18 Fixmotors Roadster"}}
    assert vo.match_hits(item, kb)[0] == []                       # the matcher alone does not read '18
    aug, found = my.for_kb_match(item)
    hits, blocked = vo.match_hits(aug, kb)
    assert [h["entry"]["id"] for h in hits] == ["x_fix_roadster"] and not blocked
    assert found[0]["basis"] == "INFERENCE"


def test_shorthand_year_outside_coverage_is_blocked_not_hit(tmp_path):
    vo, kb = _kb(tmp_path, [2013])
    aug, _ = my.for_kb_match({"category": "project_vehicle", "normalized": {"title": "MY2018 Fixmotors Roadster"}})
    hits, blocked = vo.match_hits(aug, kb)
    assert hits == [] and blocked


def test_part_number_never_becomes_a_year_in_the_matcher(tmp_path):
    vo, kb = _kb(tmp_path, [2018])
    aug, found = my.for_kb_match({"category": "project_vehicle", "normalized": {"title": "Fixmotors Roadster part MY18-4420"}})
    hits, _ = vo.match_hits(aug, kb)
    assert found == [] and hits == []
