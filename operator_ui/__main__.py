"""python -m operator_ui serve [--port N]
python -m operator_ui summary [--out-dir DIR] [--as-of ISO] [--top N]   (F-12; local files, never sent)

Talks to the spine's database (MBOS_DATABASE_URL / MBOS_SYSTEM_DATABASE_URL, as for `mbos`).
A worker (`mbos worker`) must be running to act on decisions. The UI never executes anything.
Step-up PIN for irreversible/money YES comes from MBOS_OPERATOR_PIN (unset = refuse).
"""

import argparse
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="operator_ui")
    ap.add_argument("cmd", choices=["serve", "summary"])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--out-dir", default="daily-summaries", help="summary: local directory for the .md/.html files")
    ap.add_argument("--as-of", default=None, help="summary: ISO timestamp (default now) — fixes the content for replay")
    ap.add_argument("--top", type=int, default=10, help="summary: digest rows")
    a = ap.parse_args(argv)
    if a.cmd == "summary":
        return _summary(a)

    from mbos.db.engine import app_engine

    from .backend import SpineBackend
    from .server import App, serve

    pin = os.environ.get("MBOS_OPERATOR_PIN") or None
    if not pin:
        print("note: MBOS_OPERATOR_PIN unset — YES on irreversible/money requests will be refused (fail-closed)")
    serve(App(SpineBackend(app_engine()), operator_pin=pin), port=a.port)
    return 0


def _summary(a) -> int:
    """F-12: write the daily summary to LOCAL files. Never sent anywhere."""
    from datetime import datetime, timezone

    from mbos.db.engine import app_engine

    from .backend import SpineBackend
    from .summary import build_summary, write_files

    as_of = datetime.fromisoformat(a.as_of.replace("Z", "+00:00")) if a.as_of else datetime.now(timezone.utc)
    s = build_summary(SpineBackend(app_engine()), as_of, top_n=a.top)
    for ext, path in write_files(s, a.out_dir).items():
        print(f"wrote {ext}: {path}")
    print(f"summary_hash {s['summary_hash']} (local only; not sent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
