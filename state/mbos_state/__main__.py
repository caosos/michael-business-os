"""CLI: python -m mbos_state <command>

  migrate                      apply pending migrations          (DSN: $MBOS_ADMIN_DSN)
  verify-chain [--anchor F]    in-database verify_chain           (DSN: $MBOS_DSN)
  head                         print the chain head
  anchor --out F               append the current head to an anchor log
  export-chain --out F         export the chain as JSONL
  verify-export F [--anchor F] offline verification of an export (no database)

Exit code 0 = ok, 1 = verification failed, 2 = usage/config error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg

from . import chain, migrate
from .store import StateStore


def _dsn(var: str) -> str:
    dsn = os.environ.get(var)
    if not dsn:
        print(f"error: set ${var}", file=sys.stderr)
        sys.exit(2)
    return dsn


def _last_anchor(path: str | None) -> dict | None:
    if not path or not Path(path).exists():  # first run: nothing anchored yet
        return None
    lines = [x for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    return json.loads(lines[-1]) if lines else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mbos_state")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    v = sub.add_parser("verify-chain"); v.add_argument("--anchor")
    sub.add_parser("head")
    a = sub.add_parser("anchor"); a.add_argument("--out", required=True)
    e = sub.add_parser("export-chain"); e.add_argument("--out", required=True)
    x = sub.add_parser("verify-export"); x.add_argument("path"); x.add_argument("--anchor")
    args = ap.parse_args(argv)

    if args.cmd == "migrate":
        applied = migrate.migrate(_dsn("MBOS_ADMIN_DSN"))
        print(f"{len(applied)} migration(s) applied" if applied else "schema up to date")
        return 0
    if args.cmd == "verify-export":
        ok, n, problem = chain.verify_export(Path(args.path), Path(args.anchor) if args.anchor else None)
        print(f"{'OK' if ok else 'FAILED'}: {n} receipts checked" + (f"; {problem}" if problem else ""))
        return 0 if ok else 1

    with psycopg.connect(_dsn("MBOS_DSN")) as conn:
        store = StateStore(conn)
        if args.cmd == "verify-chain":
            st = store.verify_chain(anchor=_last_anchor(args.anchor))
            print(f"{'OK' if st.ok else 'FAILED'}: {st.receipts_checked} receipts checked"
                  + (f"; seq {st.first_bad_seq}: {st.reason}" if not st.ok else ""))
            return 0 if st.ok else 1
        if args.cmd == "head":
            print(json.dumps(store.chain_head()))
            return 0
        if args.cmd == "anchor":
            print(json.dumps(chain.write_anchor(conn, Path(args.out))))
            return 0
        if args.cmd == "export-chain":
            print(f"exported {chain.export_chain(conn, Path(args.out))} receipts")
            return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
