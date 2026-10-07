"""CLI.

    python -m mbos_economics score  ITEM.json --scored-at 2026-10-07T12:00:00Z [--config-version V]
    python -m mbos_economics replay ITEM.json        # ITEM.json must carry a `scores` block
    python -m mbos_economics estimate ITEM.json --as-of 2026-10-07T18:00:00Z [--bundle BUNDLE.json]
    python -m mbos_economics digest ITEMS.json --as-of 2026-10-07T18:00:00Z [--text] [--limit N]

ITEM.json may be a bare Item v1 or an examples/*.scored.json wrapper ({item, provenance, ...}).

``score`` prints {scores, recommendation, provenance, receipt_drafts}. It writes nothing.
Exit codes: 0 ok / replay match, 1 replay mismatch, 2 invalid input or bundle, 3 estimate insufficient.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .engine import score_item
from .inputs import InputError
from .replay import replay_item


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mbos_economics")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    s.add_argument("item", type=Path)
    s.add_argument("--scored-at", required=True, help="RFC 3339 timestamp; the engine never reads the clock")
    s.add_argument("--config-version")
    r = sub.add_parser("replay")
    r.add_argument("item", type=Path)
    g = sub.add_parser("digest")
    g.add_argument("item", type=Path, help="JSON list of scored Items")
    g.add_argument("--as-of", required=True)
    g.add_argument("--text", action="store_true", help="plain-text 72-hour plan instead of JSON")
    g.add_argument("--limit", type=int)
    e = sub.add_parser("estimate")
    e.add_argument("item", type=Path)
    e.add_argument("--as-of", required=True, help="RFC 3339 timestamp; the estimator never reads the clock")
    e.add_argument("--bundle", type=Path, help="research bundle JSON (comps, evidence, overrides; all with provenance)")
    args = ap.parse_args(argv)

    item = json.loads(args.item.read_text(encoding="utf-8"))
    if args.cmd == "digest":
        from .digest import build_digest, render_text
        d = build_digest(item, args.as_of, limit=args.limit)
        print(render_text(d) if args.text else json.dumps(d, indent=2))
        return 0
    if "item" in item and "type" not in item:   # examples/*.scored.json wrapper
        item = item["item"]
    if args.cmd == "estimate":
        from .estimate import BundleError, estimate_item
        bundle = json.loads(args.bundle.read_text(encoding="utf-8")) if args.bundle else None
        try:
            out = estimate_item(item, bundle, args.as_of)
        except BundleError as e:
            print(json.dumps({"error": "invalid_bundle", "problems": e.problems}, indent=2))
            return 2
        print(json.dumps(out, indent=2))
        return 0 if out["status"] == "estimated" else 3
    if args.cmd == "score":
        try:
            out = score_item(item, load_config(args.config_version), args.scored_at)
        except InputError as e:
            print(json.dumps({"error": "invalid_input", "problems": e.problems}, indent=2))
            return 2
        print(json.dumps(out, indent=2))
        return 0
    res = replay_item(item)
    print(json.dumps(res, indent=2))
    return 0 if res["match"] else 1


if __name__ == "__main__":
    sys.exit(main())
