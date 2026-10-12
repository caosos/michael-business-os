"""F-150: GSA cards fall back to the Census gazetteer (ZIP, else 'City, ST') when lane 02's place table cannot place a lot."""
from __future__ import annotations

import copy
import json

from operator_ui import market_search as ms
from tests.test_market_f47 import ASOF, FIX, NOW

TOWNS = [("Houston", "TX", "77002"), ("Laredo", "TX", "78040"), ("Oak Ridge", "TN", "37830"), ("Oklahoma City", "OK", "73102"),
         ("Muskogee", "OK", "74401"), ("El Paso", "TX", "79901")]


def _cache(tmp_path, towns, zipcode=True):
    base = json.loads(FIX.read_text())["Results"][0]
    rows = []
    for i, (c, st, z) in enumerate(towns):
        r = copy.deepcopy(base)
        r.update(lotNo=f"{i:03d}", propertyCity=c.upper(), propertyState=st, propertyZip=z if zipcode else "")
        rows.append(r)
    p = tmp_path / "gsa.json"
    p.write_text(json.dumps({"Results": rows}))
    p.with_suffix(".asof").write_text(ASOF.isoformat())
    return str(p)


def _cards(path):
    return ms.load_gsa(path, NOW, ms._origin("Conway AR"))["cards"]


def test_lots_get_distances_by_zip_and_by_city_and_are_outside_150_miles(tmp_path):
    for zipcode in (True, False):
        cards = _cards(_cache(tmp_path, TOWNS, zipcode))
        assert len(cards) == len(TOWNS)
        assert all(c["distance"] is not None for c in cards), [(c["city"], c["distance"]) for c in cards]
        assert all(c["distance"] > 150 for c in cards)


def test_radius_counts_them_outside_not_unchecked(tmp_path):
    cards = _cards(_cache(tmp_path, TOWNS + [("Conway", "AR", "72032")]))
    near = [c for c in cards if c["distance"] is not None and c["distance"] <= 150]
    unchecked = [c for c in cards if c["distance"] is None]
    assert len(near) == 1 and not unchecked
