"""B-11: image perceptual hashing for relists and photo re-uploads (fixture images only, no network)."""

from __future__ import annotations

import io
import json
from datetime import timedelta

import pytest

pytest.importorskip("PIL")

from conftest import FIX, FLIP, T0, World  # noqa: E402
from mbos_discovery import contract  # noqa: E402
from mbos_discovery.acceptance import run_acceptance  # noqa: E402
from mbos_discovery.adapter import Normalized  # noqa: E402
from mbos_discovery.images import (DIFFERENT, INCONCLUSIVE, MATCH, NONE, FixtureImageFetcher, collect, compare,  # noqa: E402
                                   hamming, phash)
from mbos_discovery.rawstore import MemoryRawStore  # noqa: E402
from mbos_discovery.store import ItemStore  # noqa: E402

CORPUS = FIX / "corpus7d"
IMG = CORPUS / "images"


def _png(name):
    return (IMG / f"{name}.png").read_bytes()


# ---------------------------------------------------------------- the hash
def test_phash_is_deterministic_and_robust_to_reupload_degradation():
    a = _png("500000000005")
    assert phash(a) == phash(a) and len(phash(a)) == 16
    assert hamming(phash(a), phash(_png("510000000000"))) <= 10          # rescaled + cropped + posterized copy


def test_phash_separates_different_units_of_the_same_model():
    assert hamming(phash(_png("53000000001")), phash(_png("53000000002"))) >= 20


def test_phash_survives_jpeg_recompression():
    from PIL import Image
    buf = io.BytesIO()
    Image.open(io.BytesIO(_png("500000000003"))).convert("RGB").save(buf, format="JPEG", quality=60)
    assert hamming(phash(_png("500000000003")), phash(buf.getvalue())) <= 10


def test_compare_verdicts():
    a, b = phash(_png("53000000001")), phash(_png("53000000002"))
    assert compare([a], [a]) == MATCH and compare([a], [b]) == DIFFERENT
    assert compare([], [a]) == NONE and compare([a], []) == NONE
    assert compare(["0" * 16], ["000000000000ffff"]) == INCONCLUSIVE    # 16 bits apart


def test_collect_retains_skips_and_never_raises():
    raw = MemoryRawStore()
    f = FixtureImageFetcher({"https://img/a.png": IMG / "500000000001.png", "https://img/bad.png": CORPUS / "labels.json"})
    refs, hashes = collect(["https://img/a.png", "https://img/missing.png", "https://img/bad.png"], f, raw.put)
    assert len(refs) == len(hashes) == 1 and raw.get(refs[0]) == _png("500000000001")
    assert collect(["https://img/a.png"], None, raw.put) == ([], [])     # no fetcher → no image evidence


# ---------------------------------------------------------------- dedup with photos
class _Ad:
    source, ingestion_method, tos_risk, adapter_version, tool_name = "ebay", "api", "low", "t", "t"


def _n(lid, photo, seller="dealer", title="6x12 enclosed cargo trailer ramp door", price=2400.0, city="Conway"):
    return Normalized(lid, f"https://x.invalid/{lid}", "flip", "trailer", "buy_item",
                      {"title": title, "price": {"amount": price, "currency": "USD", "type": "fixed"},
                       "location": {"city": city, "state": "AR"}, "counterparty": {"role": "seller", "name": seller}},
                      match_hints={"phash": [phash(_png(photo))]} if photo else {})


def _obs(store, n, day, present, source="ebay"):
    ad = _Ad()
    ad.source = source
    prov = {"provenance_id": "prov_" + "0" * 26}
    return store.observe(ad, n, "sha256:" + "0" * 64, prov, T0 + timedelta(days=day), present_ids=frozenset(present))


def test_photos_resolve_the_relist_ambiguity():
    s = ItemStore()
    _obs(s, _n("UNIT-1", "53000000001"), 0, {"UNIT-1"})
    assert _obs(s, _n("UNIT-2", "53000000002"), 5, {"UNIT-2"}).event == "CREATED"   # different photo → new unit


def test_relist_with_reuploaded_photo_still_merges():
    s = ItemStore()
    _obs(s, _n("A", "500000000005"), 0, {"A"})
    assert _obs(s, _n("B", "510000000000"), 3, {"B"}).event == "MERGED"


def test_relist_without_photos_keeps_listing_data_rule():
    s = ItemStore()
    _obs(s, _n("A", None), 0, {"A"})
    assert _obs(s, _n("B", None), 3, {"B"}).event == "MERGED"            # stated limitation when no photos


def test_cross_source_photo_match_substitutes_for_title_but_not_price_or_place():
    s = ItemStore()
    _obs(s, _n("E1", "500000000005", title="enclosed cargo trailer 6x12"), 0, {"E1"}, source="ebay")
    reupload = _n("G1", "510000000000", title="TRAILER, CARGO, ENCLOSED, GOVT SURPLUS UNIT 12")
    assert _obs(s, reupload, 0, {"G1"}, source="gsa_auctions").event == "MERGED"    # photo re-upload, other wording
    s2 = ItemStore()
    _obs(s2, _n("E1", "500000000005"), 0, {"E1"})
    far = _n("G2", "510000000000", city="Fayetteville")
    assert _obs(s2, far, 0, {"G2"}, source="gsa_auctions").event == "CREATED"        # place must still agree


def test_different_photos_veto_a_cross_source_title_match():
    s = ItemStore()
    _obs(s, _n("E1", "53000000001"), 0, {"E1"}, source="ebay")
    assert _obs(s, _n("G1", "53000000002"), 0, {"G1"}, source="gsa_auctions").event == "CREATED"


# ---------------------------------------------------------------- pipeline + acceptance
def test_pipeline_fills_contract_images_and_retains_them(world):
    from mbos_discovery.adapters import EbayBrowseAdapter
    from mbos_discovery.pipeline import run_discovery
    day = CORPUS / "day0"
    index = json.loads((IMG / "index.json").read_text())
    fetcher = FixtureImageFetcher({u: CORPUS / rel for u, rel in index.items()})
    prof = FLIP.__class__("p", "flip", ("trailer", "equipment"), limit=200, max_pages=1)
    run_discovery([(EbayBrowseAdapter.from_fixture(day / "ebay", world.clock), prof)], world.store, world.raw,
                  world.health, world.clock(), images=fetcher)
    with_imgs = [i for i in world.store.items.values() if i["normalized"].get("images")]
    assert with_imgs and len(with_imgs) == len(world.store.items)
    for i in with_imgs:
        contract.check_item(i)
        assert all(world.raw.exists(r) for r in i["normalized"]["images"])
    assert all(u.startswith("https://i.ebayimg.com/corpus/") for u in fetcher.calls)   # fixtures only


def test_acceptance_photo_evidence_removes_the_false_merge():
    r = run_acceptance(CORPUS)
    f2 = r["F2"]
    assert r["pass"] and f2["image_evidence"]
    assert f2["false_merges"] == [] and f2["missed_duplicate_rate"] < 0.02
    assert len(f2["listing_data_only"]["false_merges"]) == 1                # the B-10 ambiguity, now resolved
    assert f2["listing_data_only"]["false_merges"][0]["objects"] == ["obj-ebay-amb-1", "obj-ebay-amb-2"]
