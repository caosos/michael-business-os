#!/usr/bin/env python3
"""F-146 entry point, kept working: a thin alias for `refresh_auction_events.py --only wooley` (F-149). Needs an explicit `--live`."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import refresh_auction_events as rae  # noqa: E402
from operator_ui.market_sources import AUCTION_SITES, cache_path  # noqa: E402


def refresh(out: Path, adapter=None) -> int:
    return rae.refresh(AUCTION_SITES["wooley"], out, adapter)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--only" not in argv:
        argv += ["--only", "wooley"]
    return rae.main(argv)


if __name__ == "__main__":
    sys.exit(main())
