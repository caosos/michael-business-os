"""Regenerate examples/asset/*.scored.json from *.input.json (C-33). Run from economics/."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mbos_economics.asset_deal import evaluate  # noqa: E402

EX = Path(__file__).resolve().parents[1] / "examples" / "asset"
for f in sorted(EX.glob("*.input.json")):
    out = f.with_name(f.name.replace(".input.", ".scored."))
    out.write_text(json.dumps(evaluate(json.loads(f.read_text())), indent=2, sort_keys=True) + "\n")
    print("wrote", out.name)
