"""`mbos` — operator CLI for the dry-run spine. The Operator UI (lane F) replaces the decision commands;
everything here goes through the same spine functions, so receipts are identical.

    mbos devdb up|down|env          project-local Postgres 16 (pgserver) for development
    mbos migrate
    mbos worker [--fixture PATH]    run DBOS: recover workflows, optionally discover a fixture, keep serving
    mbos queue                      what needs Michael's decision
    mbos show ITEM_ID
    mbos note add|list              Michael's own model knowledge (lane D; human channel only)
    mbos card ITEM_ID [--json]      the decision-ready opportunity card (ADR-0011)
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


def _owner_engine() -> sa.Engine:
    """D-26 / R14: human decisions (decide, outcome, notes, kill switch) go through the OWNER login, never the workflow login.
    With MBOS_OWNER_DATABASE_URL unset (dev, single-login reference backend) this falls back to the worker login and says so."""
    from mbos.config import settings
    from mbos.db.engine import engine_for
    from mbos.db.migrate import migrate

    url = settings().owner_database_url
    if not url:
        print("NOTE: MBOS_OWNER_DATABASE_URL is not set; using the worker login for a human action (dev only). In production set it "
              "to the owner (approver) login; the workflow login must not hold approver (D-26, R14).", file=sys.stderr)
        return _engine()
    engine = engine_for(url)
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

    if settings().owner_database_url and not a.allow_owner_dsn:
        # F-87 / R14: R14 holds in the database, but one OS process holding BOTH logins can use either. The workflow worker (the process an
        # agent-reachable workflow runs in) must start WITHOUT the owner login; the owner CLI/UI run in their own processes with it.
        print("REFUSING to start: MBOS_OWNER_DATABASE_URL is set in the workflow worker's environment. Run the worker without it "
              "(`env -u MBOS_OWNER_DATABASE_URL mbos worker`); human decisions use the owner CLI/UI process. "
              "Dev override: --allow-owner-dsn.", file=sys.stderr)
        return 2
    from mbos.production import build_components, render_report

    s = settings()
    if s.state_backend == "lane_d":
        from dbos import DBOS as _D

        comps, report = build_components(s, fixture=a.fixture, dbos=_D)
    else:
        comps = Components()
        if a.fixture:
            comps.adapters["fixture"] = FixtureSourceAdapter(a.fixture, name="fixture")
        report = [{"component": "everything", "kind": "STAND-IN",
                   "detail": "reference store and stand-ins (set MBOS_STATE_BACKEND=lane_d MBOS_GATEWAY_MODE=lane_e for the real lanes)"}]
    print("components:\n" + render_report(report))
    init_runtime(s, comps)  # launch recovers every PENDING workflow
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
            from mbos.workflows import recover_orphan_gates

            while True:
                time.sleep(60)
                recover_orphan_gates()  # F-42: periodic safety net for follow-up gates
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
        print(f"  item    {item['item_id']}   (mbos card {item['item_id']})")
        print(f"  areq    {areq['action_request_id']}   expires {areq['expires_at']}")
        print(f"  payload {areq['payload_hash']}")
        step = " (YES needs --step-up)" if areq["reversibility"] == "irreversible" else ""
        print(f"  decide: mbos decide {areq['action_request_id']} YES|NO|MODIFY|HOLD --seen {areq['payload_hash'][7:19]}{step}")
    return 0


def cmd_items(a: argparse.Namespace) -> int:
    """F-70 (07 cold-start): list Items so `card`, `show` and `outcome` have an id to use."""
    import sqlalchemy as sa

    sql = ("SELECT item_id, state, type, category, body->'normalized'->>'title', body->>'created_at' FROM mbos.items "
           + ("WHERE state = :st " if a.state else "") + "ORDER BY body->>'created_at' DESC LIMIT :n")
    with _engine().connect() as c:
        rows = c.execute(sa.text(sql), {"st": a.state, "n": a.limit}).all()
    if not rows:
        print("No items.")
    for iid, state, typ, cat, title, created in rows:
        print(f"{iid}  {state:<18} {typ}/{cat:<14} {(title or '')[:70]}")
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

    engine = _owner_engine()
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
    if a.step_up:
        kw["auth_context"] = {"method": "cli_local_confirm", "step_up": True}
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


def cmd_card(a: argparse.Namespace) -> int:
    from mbos import card as cardmod

    with _engine().connect() as c:
        item, receipts, areqs = cardmod.load_inputs(c, a.item_id)
        card = cardmod.build_card(item, receipts, areqs, cardmod.enrichment_from_item(c, item))
    errors = cardmod.validate_card(card)
    print(json.dumps(card, indent=2) if a.json else cardmod.render_text(card))
    if errors:
        print("CARD INVALID:", *errors, sep="\n  ", file=sys.stderr)
    return 1 if errors else 0


def cmd_note(a: argparse.Namespace) -> int:
    """Enter / list Michael's own model knowledge. Human channel; never an agent tool (R14)."""
    from mbos import spine_d
    from mbos.clock import now_iso

    engine = _engine() if a.action == "list" else _owner_engine()
    if a.action == "list":
        with engine.connect() as c:
            _print(spine_d.operator_notes_document(c))
        return 0
    from mbos_economics.valueadd import new_manual_note

    bundle = new_manual_note(category=a.category, makes=a.make, models=a.model, kind=a.kind, statement=a.statement,
                             entered_by=a.author, entered_at=now_iso(), basis_of_knowledge=a.basis_of_knowledge,
                             plan_hint=a.plan_hint, reference_url=a.reference_url)
    with engine.begin() as c:
        print("recorded", spine_d.record_operator_note(c, bundle))
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
    with _owner_engine().begin() as c:
        _print(spine.record_outcome(c, a.item_id, a.kind, realized=realized or None, notes=a.notes))
    return 0


def cmd_panic(a: argparse.Namespace) -> int:
    from mbos import spine

    with _owner_engine().begin() as c:
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
    s.add_argument("--allow-owner-dsn", action="store_true", help="dev only: let the worker hold the owner login too (defeats F-87)")
    s.add_argument("--settle", type=float, default=3.0); s.set_defaults(fn=cmd_worker)
    sub.add_parser("queue").set_defaults(fn=cmd_queue)
    s = sub.add_parser("items"); s.add_argument("--state"); s.add_argument("--limit", type=int, default=50); s.set_defaults(fn=cmd_items)
    s = sub.add_parser("show"); s.add_argument("item_id"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("decide"); s.add_argument("areq"); s.add_argument("decision", choices=["YES", "NO", "MODIFY", "HOLD"])
    s.add_argument("--seen", required=True, help="payload hash prefix as shown by `mbos queue`")
    s.add_argument("--reason"); s.add_argument("--change", action="append", help="MODIFY: payload key=value")
    s.add_argument("--hold-until"); s.add_argument("--renotify"); s.add_argument("--escalate")
    s.add_argument("--step-up", action="store_true",
                   help="explicit confirmation required for YES on irreversible / money-like requests")
    s.set_defaults(fn=cmd_decide)
    s = sub.add_parser("card"); s.add_argument("item_id"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_card)
    s = sub.add_parser("note"); s.add_argument("action", choices=["add", "list"]); s.add_argument("--category")
    s.add_argument("--make", action="append"); s.add_argument("--model", action="append"); s.add_argument("--kind")
    s.add_argument("--statement"); s.add_argument("--author", default="michael"); s.add_argument("--basis-of-knowledge", dest="basis_of_knowledge")
    s.add_argument("--plan-hint"); s.add_argument("--reference-url"); s.set_defaults(fn=cmd_note)
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
