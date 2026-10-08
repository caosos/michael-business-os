"""P-02-15: year-specific KB hits reach the card path with provenance; a part number never matches."""

import json

import pytest

from mbos_discovery.enrichment import kb_hits

PROV = "prov_" + "1" * 26


def _kb(tmp_path):
    vo = pytest.importorskip("mbos_economics.valueadd")
    e = {"id": "nhtsa_tsb_cub_cadet_xt1", "category": "project_vehicle",
         "match": [{"makes": ["cub cadet"], "models": ["xt1"], "years": [2018]}],
         "kind": "known_weakness", "risk": "Manufacturer issued a service bulletin for this model.",
         "source": {"title": "NHTSA bulletin 1", "url": "https://www.nhtsa.gov/", "retrieved": "2026-10-07"},
         "evidence": {"provenance_id": "prov_" + "2" * 26}}
    p = tmp_path / "kb.json"
    p.write_text(json.dumps({"kb_version": "fixture", "kb_format": 1, "entries": [e]}))
    return vo, vo.load_kb(p)


def _item(title):
    return {"category": "project_vehicle", "normalized": {"title": title}}


@pytest.mark.parametrize("title,quoted", [("2018 Cub Cadet XT1 mower", "2018"), ("'18 Cub Cadet XT1 mower", "'18"),
                                           ("Cub Cadet XT1 MY2018", "MY2018")])
def test_year_specific_hit_with_provenance(tmp_path, title, quoted):
    vo, kb = _kb(tmp_path)
    r = kb_hits(_item(title), kb, vo.match_hits, PROV)
    [h] = r["hits"]
    assert h["entry_id"] == "nhtsa_tsb_cub_cadet_xt1" and h["entry_provenance_id"] == "prov_" + "2" * 26
    y = h["year_read"]
    assert (y["value"], y["basis"], y["provenance_id"]) == (2018, "INFERENCE", PROV) and quoted in y["note"]
    assert title in y["note"]


def test_card_value_add_agrees(tmp_path):
    vo, kb = _kb(tmp_path)
    r = kb_hits(_item("'18 Cub Cadet XT1 mower"), kb, vo.match_hits, PROV)
    assert vo.match_hits(r["item_for_value_add"], kb)[0][0]["entry"]["id"] == "nhtsa_tsb_cub_cadet_xt1"


@pytest.mark.parametrize("title", ["Cub Cadet XT1 part 1890", "Cub Cadet XT1 part # 1890A", "Cub Cadet XT1 MY18-4420",
                                    "Cub Cadet XT1 part MY1890", "Cub Cadet XT1 no year"])
def test_part_number_never_matches(tmp_path, title):
    vo, kb = _kb(tmp_path)
    r = kb_hits(_item(title), kb, vo.match_hits, PROV)
    assert r["hits"] == [] and r["model_years"] == []
