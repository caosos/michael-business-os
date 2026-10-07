"""`mbos-discover` — run the DISCOVER + NORMALIZE lane from a TOML config.

    mbos-discover run    --config config/discovery.example.toml [--fixtures tests/fixtures]
                         [--source NAME]... [--dry]       (NAME: any profile source, see runner.ALL_SOURCES)
    mbos-discover health [--data-dir var/discovery]
    mbos-discover clear-freeze ebay --by michael
    mbos-discover acceptance [--corpus tests/fixtures/corpus7d] [--out report.json]   (F1-F4, offline)

State lives under --data-dir: raw/ (content-addressed payloads), items.json, health.json,
runs/<run_id>.json. Exit code 0 even when a source fails (that is reported, not fatal);
2 for a bad config.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from .health import HealthBook, UnavailablePanic
from .runner import ALL_SOURCES, ConfigError, build_plan, dry_run, run
from .store import load_json, save_json_atomic


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _panic():
    """Lane E PANIC state (B-04/B-09). Since E-02 it lives in Postgres (lane D `mbos.panic_state`, ruling R5):
    set MBOS_PANIC_STATE to a libpq DSN for a read-capable login (e.g. the reader role). Unset = local health
    only. Set but unusable (governance package missing, DB down, no rights) = every source blocked (fail closed)."""
    dsn = os.environ.get("MBOS_PANIC_STATE")
    if not dsn:
        return None
    try:
        from mbos_governance import PgPanicStore
    except ImportError as e:
        return UnavailablePanic(f"MBOS_PANIC_STATE set but mbos_governance (>= E-02) not importable: {e}")
    return PgPanicStore(dsn)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mbos-discover")
    ap.add_argument("--data-dir", default="var/discovery")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config", required=True)
    r.add_argument("--fixtures", help="fixture root (ebay/, gsa/, samgov/, trashnothing/, email/, comps/, cpsc/, nhtsa/); no network")
    r.add_argument("--source", action="append", default=[], choices=ALL_SOURCES,
                   help="only profiles of this source (repeatable)")
    r.add_argument("--dry", action="store_true",
                   help="print the exact requests a live run would make; touches no network, no state, no PANIC DB")
    sub.add_parser("health")
    acc = sub.add_parser("acceptance", help="run discovery acceptance F1-F4 on a fixture corpus (offline)")
    acc.add_argument("--corpus", default="tests/fixtures/corpus7d")
    acc.add_argument("--schema", default="docs/integration/freeze-request/freeze-request.schema.json")
    acc.add_argument("--out", help="write the full JSON report here")
    c = sub.add_parser("clear-freeze")
    c.add_argument("source")
    c.add_argument("--by", required=True, help="the human clearing the freeze")
    a = ap.parse_args(argv)

    data = Path(a.data_dir)
    hb = HealthBook.from_json(load_json(data / "health.json", {}))

    if a.cmd == "health":
        print(json.dumps(hb.to_json(), indent=1))
        return 0
    if a.cmd == "acceptance":
        from .acceptance import render, run_acceptance
        report = run_acceptance(Path(a.corpus), Path(a.schema))
        if a.out:
            save_json_atomic(Path(a.out), report)
        print(render(report))
        return 0 if report["pass"] else 1
    if a.cmd == "clear-freeze":
        hb.clear_freeze(a.source, a.by, _now())
        save_json_atomic(data / "health.json", hb.to_json())
        print(f"{a.source}: freeze cleared by {a.by}")
        return 0

    cfg_path = Path(a.config)
    try:
        cfg = tomllib.loads(cfg_path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    only = set(a.source)
    fixtures = Path(a.fixtures) if a.fixtures else None
    try:
        if a.dry:
            plan = build_plan(cfg, Path.cwd(), fixtures, True, only)
            print(dry_run(plan))
            return 0
        return run(cfg, Path.cwd(), data, fixtures, only, _panic())
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
