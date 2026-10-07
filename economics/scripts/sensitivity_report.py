"""C-09: generate the MICHAEL_DECISIONS #1/#2 sensitivity tables (report only; config untouched).

    python3 economics/scripts/sensitivity_report.py > /tmp/tables.md

Corpus: the golden scored Items (economics/examples) + Agent 02's fixture Items that the C-01/C-04
path can score (4 service leads; the Conway 6x12 trailer with the fixture sold comps). Config files are
hashed before and after; the script fails if any byte changed.
"""

import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mbos_economics.comps_feed import load_fixture_comps, research_step  # noqa: E402
from mbos_economics.config import CONFIG_DIR, load_config  # noqa: E402
from mbos_economics.estimate import apply_estimate, estimate_item  # noqa: E402
from mbos_economics.sensitivity import render_markdown, sensitivity_report  # noqa: E402

AS_OF = "2026-10-07T18:00:00Z"


def corpus() -> dict[str, dict]:
    cases = {p.name.replace(".scored.json", ""): json.loads(p.read_text())["item"]
             for p in sorted((ROOT / "examples").glob("*.scored.json"))}
    items = json.loads((ROOT / "tests" / "fixtures" / "agent02" / "items.json").read_text())
    for it in items:
        if it["type"] == "service":
            r = estimate_item(it, None, AS_OF)
            cases[f"a02_{it['category']}_lead"] = apply_estimate(it, r)
    trailer = copy.deepcopy([i for i in items if i["category"] == "trailer" and i["normalized"]["title"].startswith("6x12")][0])
    trailer["state"] = "RESEARCHING"
    comps, prov = load_fixture_comps(ROOT / "tests" / "fixtures" / "comps" / "sold_comps.json")
    cases["a02_trailer_6x12_with_sold_comps"] = research_step(trailer, comps, prov, AS_OF)["item"]
    return cases


def config_fingerprint() -> dict[str, str]:
    return {str(p.relative_to(CONFIG_DIR)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(CONFIG_DIR.rglob("*.json"))}


def main() -> None:
    before = config_fingerprint()
    rep = sensitivity_report(corpus(), load_config())
    if config_fingerprint() != before:
        raise SystemExit("config changed during a report-only run")
    print(render_markdown(rep))


if __name__ == "__main__":
    main()
