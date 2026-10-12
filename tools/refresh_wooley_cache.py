#!/usr/bin/env python3
"""F-146: refresh the Wooley auction-event cache read by /market. The ONLY place that fetches. Needs an explicit `--live`; without it the
tool refuses (exit 2) and makes no request. Fetches wooleyauctioneers.com pages only (lane 02 WooleySiteAdapter; never hibid.com).
Writes var/cache/wooley-events.json atomically: {as_of, requests, error, records}. A failed refresh never replaces a good cache with an empty one."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "var" / "cache" / "wooley-events.json"


def write_atomic(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".wooley-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def refresh(out: Path, adapter=None) -> int:
    from mbos_discovery.adapters.wooley_site import WooleySiteAdapter
    ad = adapter or WooleySiteAdapter(live=True)
    res = ad.fetch()
    as_of = ad.summary.get("as_of") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    err = {"kind": res.error.kind, "message": res.error.message} if res.error else None
    doc = {"source": "wooley_auctioneers", "as_of": as_of, "requests": res.requests_made, "error": err,
           "detail_errors": ad.summary.get("detail_errors", {}), "records": [r.payload for r in res.records]}
    if err and not doc["records"] and out.exists():
        print(f"refresh failed ({err['message']}); the existing cache is kept", file=sys.stderr)
        return 1
    write_atomic(out, doc)
    print(json.dumps({"out": str(out), "as_of": as_of, "events": len(doc["records"]), "requests": res.requests_made, "error": err}))
    return 1 if err else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="REQUIRED: really fetch wooleyauctioneers.com (about 10 s per request)")
    ap.add_argument("--out", type=Path, default=Path(os.environ.get("MBOS_WOOLEY_CACHE") or DEFAULT_OUT))
    a = ap.parse_args(argv)
    if not a.live:
        print("refused: this tool fetches only with an explicit --live; no request was made", file=sys.stderr)
        return 2
    return refresh(a.out)


if __name__ == "__main__":
    sys.exit(main())
