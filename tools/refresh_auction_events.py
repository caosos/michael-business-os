#!/usr/bin/env python3
"""F-149: refresh the auction-house event caches read by /market (one file per auctioneer). The ONLY place that fetches. Needs an explicit `--live`;
without it the tool refuses (exit 2) and makes no request. Fetches each auctioneer's own site only (lane 02 adapters; never hibid.com, bidwrangler.com
or proxibid.com). Each adapter keeps its own crawl delay; a site with an hourly cap is skipped while its cache is younger than the cap.
Writes var/cache/<name>-events.json atomically: {as_of, requests, error, records}. A failed refresh never replaces a good cache with an empty one."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from operator_ui.market_sources import AUCTION_SITES, cache_path  # noqa: E402


def write_atomic(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".events-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _age_s(out: Path, now: datetime) -> float | None:
    try:
        return (now - datetime.fromisoformat(json.loads(out.read_text())["as_of"].replace("Z", "+00:00"))).total_seconds()
    except (OSError, ValueError, KeyError, TypeError):
        return None


def refresh(site, out: Path, adapter=None, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    age = _age_s(out, now)
    if adapter is None and site.min_interval_s and age is not None and 0 <= age < site.min_interval_s:
        print(f"{site.key}: skipped, the cache is {int(age)} s old and {site.name} is fetched at most once per {int(site.min_interval_s)} s", file=sys.stderr)
        return 0
    ad = adapter or site.adapter(live=True)
    res = ad.fetch()
    as_of = ad.summary.get("as_of") or now.strftime("%Y-%m-%dT%H:%M:%SZ")
    err = {"kind": res.error.kind, "message": res.error.message} if res.error else None
    doc = {"source": site.key, "as_of": as_of, "requests": res.requests_made, "error": err,
           "detail_errors": ad.summary.get("detail_errors", {}), "records": [r.payload for r in res.records]}
    if err and not doc["records"] and out.exists():
        print(f"{site.key}: refresh failed ({err['message']}); the existing cache is kept", file=sys.stderr)
        return 1
    write_atomic(out, doc)
    print(json.dumps({"source": site.key, "out": str(out), "as_of": as_of, "events": len(doc["records"]), "requests": res.requests_made, "error": err}))
    return 1 if err else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="REQUIRED: really fetch the auctioneers' own sites (about 10 s per request)")
    ap.add_argument("--only", choices=sorted(AUCTION_SITES), help="refresh one auctioneer (default: all)")
    ap.add_argument("--out", type=Path, help="cache file (only with --only; default var/cache/<name>-events.json or the MBOS_*_CACHE variable)")
    a = ap.parse_args(argv)
    if not a.live:
        print("refused: this tool fetches only with an explicit --live; no request was made", file=sys.stderr)
        return 2
    if a.out and not a.only:
        print("refused: --out needs --only", file=sys.stderr)
        return 2
    codes = [refresh(s, a.out or Path(cache_path(s))) for k, s in AUCTION_SITES.items() if a.only in (None, k)]
    return 1 if any(codes) else 0


if __name__ == "__main__":
    sys.exit(main())
