"""Regenerate economics/examples/*.scored.json from tests/worked_cases.py.

Each file = {item (Item v1 with scores + recommendation), provenance, receipt_drafts}.
Run only when the engine or config changes on purpose; the files are golden data
that tests replay byte-for-byte.

    python3 economics/scripts/regen_examples.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from mbos_economics.config import load_config  # noqa: E402
from mbos_economics.engine import score_item  # noqa: E402
from worked_cases import ALL_CASES, SCORED_AT, fresh  # noqa: E402


def main() -> None:
    cfg = load_config()
    out_dir = ROOT / "examples"
    out_dir.mkdir(exist_ok=True)
    for name in ALL_CASES:
        it = fresh(name)
        out = score_item(it, cfg, SCORED_AT)
        it["state"] = "RECOMMENDED"
        it["scores"], it["recommendation"] = out["scores"], out["recommendation"]
        it["provenance_ids"] = sorted({s["provenance_id"] for s in it["sources"]}
                                      | {out["provenance"]["provenance_id"]})
        doc = {"item": it, "provenance": out["provenance"], "receipt_drafts": out["receipt_drafts"]}
        (out_dir / f"{name}.scored.json").write_text(json.dumps(doc, indent=2) + "\n")
        print(f"{name:34s} {out['scores']['scorecard']['decision']:5s} {out['scores']['scorecard_id']}")


if __name__ == "__main__":
    main()
