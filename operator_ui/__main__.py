"""python -m operator_ui serve [--port N]
python -m operator_ui summary [--out-dir DIR] [--as-of ISO] [--top N]   (F-12; local files, never sent)

Talks to the spine's database (MBOS_DATABASE_URL / MBOS_SYSTEM_DATABASE_URL, as for `mbos`).
A worker (`mbos worker`) must be running to act on decisions. The UI never executes anything.
Step-up PIN for irreversible/money YES comes from MBOS_OPERATOR_PIN (unset = refuse).
MBOS_STATE_BACKEND=lane_d (+ MBOS_POLICY_PATH) runs the UI on Agent 04's store with Agent 05's gateway (F-04).
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
    serve(App(make_backend(), operator_pin=pin), port=a.port)
    return 0


def ui_engine():
    """R14: MBOS_APPROVER_DATABASE_URL = a DSN for lane D's `mbos_operator_ui` login (member of `approver` only). Unset =
    the shared app engine (`mbos_dbos`, which also holds agent_write + gateway). The approver role can decide, but it
    cannot record outcomes/notes or propose follow-ups on its own; point only a decide-only deployment at it."""
    from mbos.db.engine import app_engine

    dsn = os.environ.get("MBOS_APPROVER_DATABASE_URL")
    if not dsn:
        return app_engine()
    import sqlalchemy as sa

    return sa.create_engine(dsn, pool_pre_ping=True)


def make_backend():
    """MBOS_STATE_BACKEND=reference (default) | lane_d. On lane D the UI is built with the SAME Components as the
    worker (F-04): Agent 05's PDP/gateway/kill switch via `lane_e_components`, because `spine_d.decide` classifies a
    MODIFY successor with the PDP. MBOS_POLICY_PATH = a dev policy file; unset = read lane D's `policy_current`."""
    from mbos.db.engine import app_engine

    from .backend import SpineBackend

    lane = os.environ.get("MBOS_STATE_BACKEND", "reference")
    if lane == "reference":
        return SpineBackend(ui_engine())
    if lane != "lane_d":
        raise SystemExit(f"MBOS_STATE_BACKEND must be 'reference' or 'lane_d', got {lane!r}")
    from mbos.adapters.governance import lane_e_components
    from mbos.config import settings

    import dataclasses

    from mbos.runtime import init_runtime

    s = dataclasses.replace(settings(), state_backend="lane_d", gateway_mode="lane_e")
    comps, _gov = lane_e_components(s.database_url, os.environ.get("MBOS_POLICY_PATH") or None)
    # F-11: `workflows.propose_followup` needs an initialised runtime in THIS process. launch=False: the UI never runs
    # workflows (a worker does); the request's approval gate is enqueued through a DBOS client.
    rt = init_runtime(s, comps, launch=False)
    return SpineBackend(ui_engine(), rt.components, lane="lane_d")


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
