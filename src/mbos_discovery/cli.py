"""`mbos-discover` — run the DISCOVER + NORMALIZE lane from a TOML config.

    mbos-discover run    --config config/discovery.example.toml [--fixtures tests/fixtures]
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

from .adapter import SearchProfile
from .adapters import EbayBrowseAdapter, GsaAuctionsAdapter, SamGovAdapter, ServiceIntakeAdapter, TrashNothingAdapter
from .health import HealthBook, UnavailablePanic
from .pipeline import run_discovery
from .rawstore import FileRawStore
from .store import ItemStore, load_json, save_json_atomic


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


def build_jobs(cfg: dict, base: Path, fixtures: Path | None):
    jobs = []
    for p in cfg.get("profile", []):
        src = p["source"]
        profile = SearchProfile(
            profile_id=p["id"], lane=p["lane"], keywords=tuple(p.get("keywords", [])),
            postal_code=str(p.get("postal_code", "72034")), radius_miles=int(p.get("radius_miles", 100)),
            max_price=p.get("max_price"), limit=int(p.get("limit", 50)), max_pages=int(p.get("max_pages", 2)))
        live = bool(p.get("live", False))      # GSA / Trash Nothing: no live call unless the profile says so
        if src == "ebay":
            adapter = (EbayBrowseAdapter.from_fixture(fixtures / "ebay", _now) if fixtures
                       else EbayBrowseAdapter.from_env(os.environ, clock=_now))
        elif src == "gsa_auctions":
            states = frozenset(p["states"]) if p.get("states") else None
            kw = {"states": states} if states else {}
            adapter = (GsaAuctionsAdapter.from_fixture(fixtures / "gsa", _now, **kw) if fixtures
                       else GsaAuctionsAdapter.from_env(os.environ, live=live, clock=_now, **kw))
        elif src == "samgov":
            states = tuple(p.get("states") or ["AR"])
            adapter = (SamGovAdapter.from_fixture(fixtures / "samgov", _now, states=states) if fixtures
                       else SamGovAdapter.from_env(os.environ, live=live, clock=_now, states=states))
        elif src == "trashnothing":
            adapter = (TrashNothingAdapter.from_fixture(fixtures / "trashnothing", _now) if fixtures
                       else TrashNothingAdapter.from_env(os.environ, live=live, clock=_now))
        elif src in ("website_lead", "referral"):
            adapter = ServiceIntakeAdapter(src, base / p["inbox"], _now)
        else:
            raise SystemExit(f"config: no adapter implemented for source {src!r} (profile {p['id']})")
        jobs.append((adapter, profile))
    return jobs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mbos-discover")
    ap.add_argument("--data-dir", default="var/discovery")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config", required=True)
    r.add_argument("--fixtures", help="fixture root (ebay/, gsa/, trashnothing/ subdirs); no network")
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
    jobs = build_jobs(cfg, Path.cwd(), Path(a.fixtures) if a.fixtures else None)
    store = ItemStore.from_json(load_json(data / "items.json", {}))
    report = run_discovery(jobs, store, FileRawStore(data / "raw"), hb, _now(),
                           frozenset(cfg.get("enabled_sources", [])), panic=_panic())
    save_json_atomic(data / "items.json", store.to_json())
    save_json_atomic(data / "health.json", hb.to_json())
    save_json_atomic(data / "runs" / f"{report.run_id}.json", report.to_json())

    for s in report.sources:
        line = (f"{s.source:<13} {s.profile_id:<22} {s.status:<7} fetched={s.fetched} new={s.created} "
                f"merged={s.merged} updated={s.updated} seen={s.seen} quarantined={s.quarantined}")
        detail = s.skipped_reason or (s.error or {}).get("message")
        print(line + (f"  [{detail}]" if detail else ""))
    for f in report.freeze_requests:
        print(f"FREEZE REQUEST {f['capability']}: {f['reason']}  (apply: mbos-gov panic freeze --level L2 "
              f"--target {f['capability']} --actor {f['requested_by']} --reason ...)")
    print(f"items in store: {len(store.items)}  run: {report.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
