"""B-10: discovery acceptance F1–F4 as a runnable harness (agent-01-integration §8-F), plus the relist rule that
F2 depends on — and its one known ambiguity, stated rather than hidden."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import FIX, T0
from mbos_discovery.acceptance import run_acceptance
from mbos_discovery.adapter import Normalized
from mbos_discovery.store import ItemStore

CORPUS = FIX / "corpus7d"
SCHEMA = Path(__file__).resolve().parents[1] / "docs" / "integration" / "freeze-request" / "freeze-request.schema.json"


def test_harness_passes_and_reports_f2_rate():
    r = run_acceptance(CORPUS, SCHEMA)
    assert r["pass"], json.dumps({k: r[k]["pass"] for k in ("F1", "F2", "F3", "F4")})
    f2 = r["F2"]
    assert f2["missed_duplicate_rate"] < 0.02 and f2["false_merges"] == [] and f2["unlabeled"] == []
    assert (f2["items"], f2["objects"], f2["sightings_labelled"]) == (38, 38, 43)
    assert r["F3"]["schema_checked"] and r["F4"]["fetched_despite_forbidden"] == []


def test_corpus_is_reproducible(tmp_path):
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, "-I", str(root / "tools" / "make_corpus.py"), str(tmp_path / "c")], check=True)
    from mbos_discovery.images import phash
    for p in sorted(CORPUS.rglob("*")):
        if not p.is_file():
            continue
        q = tmp_path / "c" / p.relative_to(CORPUS)
        if p.suffix == ".png":       # PNG bytes may vary with the zlib/Pillow build; the photo must not
            assert phash(q.read_bytes()) == phash(p.read_bytes()), p
        else:
            assert q.read_bytes() == p.read_bytes(), p


def test_cli_exit_code_and_report(tmp_path):
    from mbos_discovery.cli import main
    out = tmp_path / "report.json"
    assert main(["acceptance", "--corpus", str(CORPUS), "--schema", str(SCHEMA), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["F2"]["missed_duplicate_rate"] == 0.0


# ---------------------------------------------------------------- relist rule, edge by edge
class _Ad:
    source, ingestion_method, tos_risk, adapter_version, tool_name = "ebay", "api", "low", "t", "t"


def _n(lid, seller="dealer", title="6x12 enclosed trailer ramp door", price=2000.0):
    return Normalized(lid, f"https://x.invalid/{lid}", "flip", "trailer", "buy_item",
                      {"title": title, "price": {"amount": price, "currency": "USD", "type": "fixed"},
                       "counterparty": {"role": "seller", "name": seller} if seller else {"role": "seller"}})


def _observe(store, n, day, present):
    from datetime import timedelta
    prov = {"provenance_id": f"prov_{'0' * 20}{n.source_listing_id:0>6}"[:31]}
    return store.observe(_Ad(), n, "sha256:" + "0" * 64, prov, T0 + timedelta(days=day), present_ids=frozenset(present))


def test_relist_merges_only_when_original_ended():
    s = ItemStore()
    _observe(s, _n("A"), 0, {"A"})
    assert _observe(s, _n("B"), 3, {"B"}).event == "MERGED"              # A absent from the fetch → relist


def test_twins_present_together_never_merge():
    s = ItemStore()
    _observe(s, _n("A"), 0, {"A", "B"})
    assert _observe(s, _n("B"), 0, {"A", "B"}).event == "CREATED"


def test_relist_needs_same_seller_price_and_title():
    for cand in (_n("B", seller="someone_else"), _n("B", seller=None), _n("B", price=2600.0),
                 _n("B", title="7x14 tandem enclosed trailer")):
        s = ItemStore()
        _observe(s, _n("A"), 0, {"A"})
        assert _observe(s, cand, 3, {"B"}).event == "CREATED", cand


def test_relist_window_is_14_days():
    s = ItemStore()
    _observe(s, _n("A"), 0, {"A"})
    assert _observe(s, _n("B"), 15, {"B"}).event == "CREATED"


def test_known_ambiguity_second_identical_unit_after_first_ended():
    """From LISTING DATA ALONE a dealer's SECOND identical unit listed after the first ended is indistinguishable
    from a relist, so it merges (no data lost; inventory undercounted). B-11 resolves it when photos exist — see
    test_b11_images.py::test_photos_resolve_the_relist_ambiguity. Still true without photos (or same stock photo)."""
    s = ItemStore()
    _observe(s, _n("UNIT-1"), 0, {"UNIT-1"})
    obs = _observe(s, _n("UNIT-2"), 5, {"UNIT-2"})
    assert obs.event == "MERGED"
    assert {x["source_listing_id"] for x in s.items[obs.item_id]["sources"]} == {"UNIT-1", "UNIT-2"}
