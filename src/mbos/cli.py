"""`mbos` — operator CLI for the dry-run spine. The Operator UI (lane F) replaces the decision commands;
everything here goes through the same spine functions, so receipts are identical.

    mbos devdb up|down|env          project-local Postgres 16 (pgserver) for development
    mbos migrate
    mbos worker [--fixture PATH]    run DBOS: recover workflows, optionally discover a fixture, keep serving
    mbos queue                      what needs Michael's decision
    mbos show ITEM_ID
    mbos decide AREQ_ID YES|NO|MODIFY|HOLD --seen HASHPREFIX [--reason ..] [--change k=v ..] [--hold-until ISO]
    mbos ping ITEM_ID               wake a HOLD that has wake_on=michael_ping
    mbos outcome ITEM_ID KIND [--revenue N --cost N --hours N --notes ..]
    mbos panic on|off [--key global_freeze|capability_freeze:<cap>|agent_freeze:<agent>] --reason ..
    mbos audit                      chain + provenance + dry-run + contract conformance (exit 1 on any failure)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import sqlalchemy as sa

DEVDB_DIR = Path(os.environ.get("MBOS_DEVDB_DIR", ".pgdata"))


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


# ---------------------------------------------------------------- devdb
def _devdb_urls(server) -> tuple[str, str]:
    base = server.get_uri()
    return base.replace("/postgres?", "/mbos_app?"), base.replace("/postgres?", "/mbos_sys?")


def cmd_devdb(a: argparse.Namespace) -> int:
    import pgserver  # dev dependency

    if a.action == "down":
        pgserver.get_server(DEVDB_DIR, cleanup_mode="stop").cleanup()
        print("dev postgres stopped")
        return 0
    server = pgserver.get_server(DEVDB_DIR, cleanup_mode=None)  # keep running after this process exits
    for name in ("mbos_app", "mbos_sys"):
        if name not in server.psql(f"SELECT datname FROM pg_database WHERE datname = '{name}';"):
            server.psql(f"CREATE DATABASE {name};")
    app, sysdb = _devdb_urls(server)
    print(f"export MBOS_DATABASE_URL='{app}'\nexport MBOS_SYSTEM_DATABASE_URL='{sysdb}'")
    return 0


# ---------------------------------------------------------------- helpers
def _engine() -> sa.Engine:
    from mbos.db.engine import app_engine
    from mbos.db.migrate import migrate

    engine = app_engine()
    migrate(engine)
    return engine


def _components():
    from mbos.runtime import Components

    return Components().with_defaults()


def _wake(item_id: str, message: dict) -> None:
    from mbos.runtime import client, item_workflow_id
    from mbos.workflows import DECISION_TOPIC

    c = client()
    try:
        c.send(item_workflow_id(item_id), message, topic=DECISION_TOPIC)
    finally:
        c.destroy()


# ---------------------------------------------------------------- commands
def cmd_migrate(a: argparse.Namespace) -> int:
    from mbos.db.engine import app_engine
    from mbos.db.migrate import migrate

    print("applied:", migrate(app_engine()) or "nothing (up to date)")
    return 0


def cmd_worker(a: argparse.Namespace) -> int:
    from dbos import DBOS, SetWorkflowID

    from mbos import workflows
    from mbos.config import settings
    from mbos.reference.fixture_adapter import FixtureSourceAdapter
    from mbos.runtime import Components, init_runtime

    comps = Components()
    if a.fixture:
        comps.adapters["fixture"] = FixtureSourceAdapter(a.fixture, name="fixture")
    init_runtime(settings(), comps)  # launch recovers every PENDING workflow
    print("worker up (DRY-RUN). Recovered pending workflows; Ctrl-C to stop — parked workflows resume next start.")
    if a.fixture:
        wf_id = f"discover:fixture:{int(time.time())}"
        with SetWorkflowID(wf_id):
            results = DBOS.start_workflow(workflows.discover, "fixture").get_result()
        _print({"discover": wf_id, "results": results})
    try:
        if a.once:
            time.sleep(a.settle)
        else:
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    # Workflows parked at the approval gate run on non-daemon DBOS threads, so a normal interpreter exit
    # would block forever. Stopping hard is safe by design: they stay PENDING and resume on the next start.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def cmd_queue(a: argparse.Namespace) -> int:
    from mbos.spine import pending_decisions

    with _engine().connect() as c:
        rows = pending_decisions(c)
    if not rows:
        print("Nothing needs a decision.")
    for r in rows:
        areq, item = r["action_request"], r["item"]
        card = (item.get("scores") or {}).get("scorecard", {})
        d = card.get("derived", {})
        print(f"\n[{areq['status'].upper()}] {item['normalized']['title']}  ({item['type']}/{item['category']})")
        print(f"  verdict {item['recommendation']['verdict']}  composite {card.get('composite')}  "
              f"EV ${d.get('ev_net_profit')}  ${d.get('ev_profit_per_hour')}/h  confidence {d.get('confidence')}")
        for line in item["recommendation"]["rationale"]:
            print(f"    - {line}")
        print(f"  action  {areq['capability']} (tier {areq['tier']}, {areq['reversibility']}): {areq['payload']['summary']}")
        print(f"  areq    {areq['action_request_id']}   expires {areq['expires_at']}")
        print(f"  payload {areq['payload_hash']}")
        print(f"  decide: mbos decide {areq['action_request_id']} YES|NO|MODIFY|HOLD --seen {areq['payload_hash'][7:19]}")
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    from mbos.ledger import load_item, load_receipts

    with _engine().connect() as c:
        item = load_item(c, a.item_id)
        receipts = load_receipts(c, "item_id = :i", {"i": a.item_id})
    _print({"item": item, "receipts": [{k: r.get(k) for k in ("seq", "type", "intent", "actor", "ts")} for r in receipts]})
    return 0


def cmd_decide(a: argparse.Namespace) -> int:
    from mbos import spine

    engine = _engine()
    with engine.connect() as c:
        h = c.execute(sa.text("SELECT payload_hash FROM mbos.action_requests WHERE action_request_id = :a"),
                      {"a": a.areq}).scalar_one_or_none()
    if h is None:
        print(f"unknown action request {a.areq}", file=sys.stderr)
        return 2
    if len(a.seen) < 12 or not h[7:].startswith(a.seen.removeprefix("sha256:")):
        print("--seen does not match the request's payload hash (>= 12 hex chars). Re-read `mbos queue`.", file=sys.stderr)
        return 2
    kw: dict[str, Any] = {"channel": "cli", "reason": a.reason}
    if a.change:
        kw["payload_changes"] = dict(kv.split("=", 1) for kv in a.change)
    if a.decision == "HOLD":
        kw["hold"] = {k: v for k, v in {"hold_until": a.hold_until, "renotify_after": a.renotify,
                                        "escalate_after": a.escalate}.items() if v}
    with engine.begin() as c:
        out = spine.decide(c, a.areq, a.decision, h, _components(), **kw)
    _wake(out["item_id"], {"kind": "decision", "approval_id": out["approval"]["approval_id"]})
    _print(out)
    return 0


def cmd_ping(a: argparse.Namespace) -> int:
    _wake(a.item_id, {"kind": "ping"})
    print("pinged", a.item_id)
    return 0


def cmd_outcome(a: argparse.Namespace) -> int:
    from mbos import spine

    realized = {k: v for k, v in {"revenue": a.revenue, "total_cost": a.cost, "hours": a.hours}.items() if v is not None}
    if a.revenue is not None and a.cost is not None:
        realized["net_profit"] = a.revenue - a.cost
    with _engine().begin() as c:
        _print(spine.record_outcome(c, a.item_id, a.kind, realized=realized or None, notes=a.notes))
    return 0


def cmd_panic(a: argparse.Namespace) -> int:
    from mbos import spine

    with _engine().begin() as c:
        _print(spine.set_kill_switch(c, a.key, a.state == "on", reason=a.reason))
    return 0


def cmd_audit(a: argparse.Namespace) -> int:
    from mbos.audit import full_audit

    with _engine().connect() as c:
        res = full_audit(c)
    res["conformance"]["failures"] = res["conformance"]["failures"][:20]
    _print(res)
    return 0 if all(res[k]["ok"] for k in ("chain", "provenance", "dry_run", "conformance")) else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mbos", description="Michael Business OS — dry-run spine operator CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("devdb"); s.add_argument("action", choices=["up", "down", "env"]); s.set_defaults(fn=cmd_devdb)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    s = sub.add_parser("worker"); s.add_argument("--fixture"); s.add_argument("--once", action="store_true")
    s.add_argument("--settle", type=float, default=3.0); s.set_defaults(fn=cmd_worker)
    sub.add_parser("queue").set_defaults(fn=cmd_queue)
    s = sub.add_parser("show"); s.add_argument("item_id"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("decide"); s.add_argument("areq"); s.add_argument("decision", choices=["YES", "NO", "MODIFY", "HOLD"])
    s.add_argument("--seen", required=True, help="payload hash prefix as shown by `mbos queue`")
    s.add_argument("--reason"); s.add_argument("--change", action="append", help="MODIFY: payload key=value")
    s.add_argument("--hold-until"); s.add_argument("--renotify"); s.add_argument("--escalate"); s.set_defaults(fn=cmd_decide)
    s = sub.add_parser("ping"); s.add_argument("item_id"); s.set_defaults(fn=cmd_ping)
    s = sub.add_parser("outcome"); s.add_argument("item_id"); s.add_argument("kind")
    s.add_argument("--revenue", type=float); s.add_argument("--cost", type=float); s.add_argument("--hours", type=float)
    s.add_argument("--notes"); s.set_defaults(fn=cmd_outcome)
    s = sub.add_parser("panic"); s.add_argument("state", choices=["on", "off"]); s.add_argument("--key", default="global_freeze")
    s.add_argument("--reason", required=True); s.set_defaults(fn=cmd_panic)
    sub.add_parser("audit").set_defaults(fn=cmd_audit)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
