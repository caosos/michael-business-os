"""Regenerate economics/examples/class_aware/*.scored.json (C-19 goldens from Michael's three examples).

    python3 economics/scripts/regen_class_examples.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from class_cases import CLASS_CASES, fresh  # noqa: E402
from mbos_economics.config import load_config  # noqa: E402
from mbos_economics.engine import score_item  # noqa: E402
from worked_cases import SCORED_AT  # noqa: E402


def main() -> None:
    cfg = load_config()
    out_dir = ROOT / "examples" / "class_aware"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in CLASS_CASES:
        it = fresh(name)
        out = score_item(it, cfg, SCORED_AT)
        it["state"] = "RECOMMENDED"
        it["scores"], it["recommendation"] = out["scores"], out["recommendation"]
        it["provenance_ids"] = sorted({s["provenance_id"] for s in it["sources"]}
                                      | {out["provenance"]["provenance_id"]})
        doc = {"item": it, "provenance": out["provenance"], "receipt_drafts": out["receipt_drafts"]}
        (out_dir / f"{name}.scored.json").write_text(json.dumps(doc, indent=2) + "\n")
        sc = out["scores"]["scorecard"]
        print(f"{name:24s} {sc['decision']:5s} {sc['derived']['deal_class']:24s} rank {sc['ranking']['rank_score']}")


if __name__ == "__main__":
    main()
