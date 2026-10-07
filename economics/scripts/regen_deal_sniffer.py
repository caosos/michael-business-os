"""Regenerate economics/examples/deal_sniffer/*.json (C-15 goldens): the enrichment blocks for the
zero-turn mower (needs a trailer), the concrete saw and the utility trailer. Illustrative fixtures only.

    python3 economics/scripts/regen_deal_sniffer.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import deal_cases as dc  # noqa: E402

from mbos_economics.comps_feed import research_step  # noqa: E402
from mbos_economics.config import load_config  # noqa: E402
from mbos_economics.enrich import build_enrichment, load_seasonality  # noqa: E402
from mbos_economics.estimate import load_priors  # noqa: E402


def main() -> None:
    cfg, pri, sea = load_config(), load_priors(), load_seasonality()
    out = ROOT / "examples" / "deal_sniffer"
    out.mkdir(parents=True, exist_ok=True)
    for name, make in dc.CASES.items():
        it, comps, prov = make()
        item = research_step(it, comps, prov, dc.AS_OF, profile=dc.PROFILE)["item"]
        e = build_enrichment(item, dc.AS_OF, cfg=cfg, priors=pri, seasonality=sea, profile=dc.PROFILE)
        doc = {"_note": "C-15 golden. Illustrative fixture data; blocks are what spine.record_enrichment attaches.",
               "as_of": dc.AS_OF, "item_id": item["item_id"], "title": item["normalized"]["title"],
               "verdict": item["scores"]["scorecard"]["decision"], "blocks": e["blocks"], "omitted": e["omitted"],
               "provenance": e["provenance"], "enrichment_hash": e["enrichment_hash"]}
        (out / f"{name}.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        print(f"{name:18s} {doc['verdict']:6s} seasonality={e['blocks'].get('seasonality', {}).get('demand_now', {}).get('value')}")


if __name__ == "__main__":
    main()
