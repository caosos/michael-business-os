"""CLI.

    python -m mbos_economics score  ITEM.json --scored-at 2026-10-07T12:00:00Z [--config-version V]
    python -m mbos_economics replay ITEM.json        # ITEM.json must carry a `scores` block
    python -m mbos_economics estimate ITEM.json --as-of 2026-10-07T18:00:00Z [--bundle BUNDLE.json]
    python -m mbos_economics digest ITEMS.json --as-of 2026-10-07T18:00:00Z [--text] [--limit N]
    python -m mbos_economics audit EXPORT.json     # {items, receipts} (lane-D export) or a list of Items
    python -m mbos_economics note new --category mower --make "john deere" --model X380 --kind known_weakness \
        --statement "..." --entered-by michael --entered-at 2026-10-07T20:00:00Z --basis-of-knowledge "own experience"
    python -m mbos_economics note check NOTES.json     # validate a mechanic-notes document
    python -m mbos_economics audit --dsn "host=... dbname=mbos user=agent_read" [--strict]   # live lane-D DB

ITEM.json may be a bare Item v1 or an examples/*.scored.json wrapper ({item, provenance, ...}).

``score`` prints {scores, recommendation, provenance, receipt_drafts}. It writes nothing.
Exit codes: 0 ok / replay match / audit clean, 1 replay mismatch or audit drift, 2 invalid input, bundle or note,
3 estimate insufficient.
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
    nt = sub.add_parser("note", help="Michael's own mechanic notes (manual entry path; writes nothing)")
    nsub = nt.add_subparsers(dest="note_cmd", required=True)
    nn = nsub.add_parser("new")
    for flag in ("--category", "--kind", "--statement", "--entered-by", "--entered-at", "--basis-of-knowledge"):
        nn.add_argument(flag, required=True)
    nn.add_argument("--make", action="append", required=True, dest="makes")
    nn.add_argument("--model", action="append", required=True, dest="models")
    nn.add_argument("--plan-hint")
    nn.add_argument("--reference-url")
    nc = nsub.add_parser("check")
    nc.add_argument("notes_file", type=Path)
    a = sub.add_parser("audit")
    a.add_argument("item", type=Path, nargs="?", help="lane-D export {items, receipts} or a JSON list of scored Items")
    a.add_argument("--dsn", help="read a live lane-D database (SELECT only; needs psycopg)")
    a.add_argument("--strict", action="store_true", help="treat receipts without payload_hash as drift")
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

    if args.cmd == "note":
        from .valueadd import NoteError, load_manual_notes, new_manual_note
        try:
            if args.note_cmd == "new":
                out = new_manual_note(category=args.category, makes=args.makes, models=args.models, kind=args.kind,
                                      statement=args.statement, entered_by=args.entered_by, entered_at=args.entered_at,
                                      basis_of_knowledge=args.basis_of_knowledge, plan_hint=args.plan_hint,
                                      reference_url=args.reference_url)
                print(json.dumps(out, indent=2))     # the caller persists out["provenance"] FIRST, then stores out["note"]
            else:
                notes = load_manual_notes(args.notes_file)
                print(json.dumps({"ok": True, "active_notes": len(notes)}, indent=2))
        except NoteError as e:
            print(json.dumps({"error": "invalid_note", "problems": e.problems}, indent=2))
            return 2
        return 0
    if args.cmd == "audit":
        from .replay_audit import audit, load_scored_items
        if args.dsn:
            import psycopg  # optional dependency, only for --dsn
            with psycopg.connect(args.dsn) as conn:
                items, receipts = load_scored_items(conn)
        elif args.item:
            doc = json.loads(args.item.read_text(encoding="utf-8"))
            items, receipts = (doc["items"], doc.get("receipts")) if isinstance(doc, dict) else (doc, None)
        else:
            ap.error("audit needs EXPORT.json or --dsn")
        rep = audit(items, receipts=receipts, strict=args.strict)
        print(json.dumps({k: v for k, v in rep.items() if k != "rows"} |
                         {"drift": [r for r in rep["rows"] if any(f["drift"] for f in r["findings"])],
                          "engine_changes": [r for r in rep["rows"] if any(f["kind"] == "engine_change" for f in r["findings"])],
                          "weak_receipts": [r["item_id"] for r in rep["rows"] if any(f["kind"] == "receipt_weak" for f in r["findings"])],
                          "not_engine": [r["item_id"] for r in rep["rows"] if any(f["kind"] == "not_engine_scorecard" for f in r["findings"])]},
                         indent=2))
        return 0 if rep["ok"] else 1
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
