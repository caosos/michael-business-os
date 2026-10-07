"""C-15 Deal Sniffer cases: Items + FACT sold comps, built through the real research_step.

Illustrative fixture data only (example.invalid URLs, synthetic listings and prices).
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
AS_OF = "2026-10-07T18:00:00Z"        # October: weak mower month, normal concrete-saw month
PROFILE = json.loads((HERE / "contracts" / "operator_profile.v1.json").read_text())


def _ulid(prefix: str, n: int) -> str:
    return f"{prefix}_01JK{n:022d}"


def comps_for(category: str, title: str, prices: list[int], start: int, condition: str = "used") -> tuple[list, list]:
    comps, prov = [], []
    for i, p in enumerate(prices):
        pid = _ulid("prov", start + i)
        url = f"https://example.invalid/sold/{category}/{start + i}"
        comps.append({"kind": "sold", "price": p, "sold_date": f"2026-09-{10 + i:02d}", "source": "manual", "url": url,
                      "fetched_at": "2026-10-07T11:00:00Z", "provenance_id": pid, "category": category,
                      "title": title, "condition": condition, "currency": "USD", "dom_days": 8 + 3 * i})
        prov.append({"provenance_id": pid, "created_at": "2026-10-07T11:00:00Z", "actor_type": "human", "human_actor": "michael",
                     "basis": "FACT", "source_uri": url, "fetched_at": "2026-10-07T11:00:00Z"})
    return comps, prov


def item(n: int, category: str, title: str, ask: float, miles: float, *, city: str = "Conway", condition: str = "used") -> dict:
    return {
        "item_id": _ulid("itm", n), "schema_version": "1.0.0", "type": "flip", "category": category,
        "state": "RESEARCHING", "created_at": "2026-10-07T10:00:00Z", "updated_at": "2026-10-07T10:00:00Z",
        "sources": [{"source": "ebay", "url": f"https://example.invalid/listing/{n}", "ingestion_method": "api",
                     "first_seen_at": "2026-10-07T10:00:00Z", "provenance_id": _ulid("prov", n * 100)}],
        "dedup_key": f"{category}|deal-sniffer|{n}",
        "normalized": {"title": title, "condition": condition, "price": {"amount": ask, "currency": "USD", "type": "fixed"},
                       "location": {"city": city, "state": "AR", "road_miles_one_way": miles}},
    }


def zero_turn_mower(miles: float = 25, ask: float = 700) -> tuple[dict, list, list]:
    it = item(1, "mower", "Cub Cadet 54 in zero turn mower, deck needs rebuild", ask, miles)
    comps, prov = comps_for("mower", "54 in zero turn mower", [1750, 1850, 1950, 2050, 2150], 10)
    return it, comps, prov


def concrete_saw(miles: float = 25, ask: float = 1400) -> tuple[dict, list, list]:
    it = item(2, "mechanical_equipment", "Husqvarna FS 400 walk-behind concrete saw, blade guard cracked", ask, miles)
    comps, prov = comps_for("mechanical_equipment", "walk-behind concrete saw", [2600, 2900, 3100, 3400], 30)
    return it, comps, prov


def utility_trailer(miles: float = 20, ask: float = 700) -> tuple[dict, list, list]:
    it = item(3, "trailer", "6x12 enclosed utility trailer, needs lights", ask, miles)
    comps, prov = comps_for("trailer", "6x12 enclosed trailer", [1900, 2000, 2100], 50)
    return it, comps, prov


CASES = {"zero_turn_mower": zero_turn_mower, "concrete_saw": concrete_saw, "utility_trailer": utility_trailer}


# ---- C-16: titles that name a model (seller-stated). Illustrative fixtures only.
def recalled_cub_cadet(ask: float = 2400) -> tuple[dict, list, list]:
    it = item(4, "mower", "2018 Cub Cadet RZT SX 54 EFI zero turn mower 17AWCBYS010, tank neck leaking", ask, 25)
    comps, prov = comps_for("mower", "Cub Cadet RZT SX zero turn mower", [3200, 3350, 3500, 3650, 3800], 70)
    return it, comps, prov


def recalled_generac(ask: float = 650) -> tuple[dict, list, list]:
    it = item(5, "generator", "Generac GP6500E 6500 watt portable generator, barely used", ask, 30)
    comps, prov = comps_for("generator", "6500w portable generator", [800, 850, 900], 90)
    return it, comps, prov


def generac_gp7500e(ask: float = 650) -> tuple[dict, list, list]:
    it = item(6, "generator", "Generac GP7500E 7500 watt portable generator", ask, 30)
    comps, prov = comps_for("generator", "7500w portable generator", [900, 950, 1000], 110)
    return it, comps, prov


def campbell_compressor(ask: float = 120) -> tuple[dict, list, list]:
    it = item(7, "compressor", "Campbell Hausfeld HU200099AV 20 gallon air compressor", ask, 15)
    comps, prov = comps_for("compressor", "20 gallon air compressor", [220, 240, 260], 130)
    return it, comps, prov


VALUE_ADD_CASES = {"recalled_cub_cadet": recalled_cub_cadet, "recalled_generac": recalled_generac,
                   "generac_gp7500e": generac_gp7500e, "campbell_compressor": campbell_compressor}
