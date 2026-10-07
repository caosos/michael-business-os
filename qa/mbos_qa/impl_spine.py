"""REAL implementation under test: Agent 01's spine (`mbos`), installed from a pinned commit (`qa/impl_spine_PIN`),
on PostgreSQL 16 (pgserver). Task G-02, `MBOS_QA_IMPL=mbos_qa.impl_spine:build`.

Nothing in this module re-implements the product. Every state change, decision, guard check and receipt is
produced by `mbos.workflows` / `mbos.spine` / `mbos.ledger` / `mbos.reference.*`. This adapter only:
  * starts PostgreSQL, launches the real DBOS runtime once per process, and makes fresh migrated databases;
  * feeds 01's own fixture listings through the real `workflows.discover` (unique per call);
  * reads state back with SQL, and counts effector *invocations* by wrapping (not replacing) the effector;
  * provides superuser-only fault and tamper hooks that the acceptance tests need (labelled as such).

Two modes:
  * `flow`: the shared, launched DBOS runtime, used for decisions → durable approval gate → gateway → receipts.
  * `ledger()`: a fresh migrated database with no DBOS, seeded through the real `spine` functions, used for
    destructive tests (tamper, mutation, fault injection) so they never damage the shared chain.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict
from typing import Any

QA_ROOT = pathlib.Path(__file__).resolve().parent.parent
PIN = (QA_ROOT / "impl_spine_PIN").read_text().strip()
os.environ.setdefault("MBOS_CONTRACTS_DIR", str(QA_ROOT / "contracts"))  # F-16: non-editable install needs this

import sqlalchemy as sa  # noqa: E402

STEP_UP = {"method": "qa_step_up", "step_up": True}
IMPLEMENTATION = f"REAL: Agent 01 spine `mbos` @ {PIN[:7]} on PostgreSQL 16 (pgserver) + DBOS"


class Refused(Exception):
    """The implementation refused a decision (normalises `mbos.spine.DecisionRefused`)."""


# ------------------------------------------------------------------ process-wide resources
_LOCK = threading.RLock()
_STATE: dict[str, Any] = {}
INVOCATIONS: dict[str, int] = {}  # idempotency_key → number of DryRunEffector.execute calls in THIS process


def _wrap_effector() -> None:
    import mbos.reference.governance as g

    if getattr(g.DryRunEffector.execute, "_qa_wrapped", False):
        return
    original = g.DryRunEffector.execute

    def counted(self, engine, areq):
        INVOCATIONS[areq["idempotency_key"]] = INVOCATIONS.get(areq["idempotency_key"], 0) + 1
        return original(self, engine, areq)

    counted._qa_wrapped = True
    g.DryRunEffector.execute = counted


def server():
    with _LOCK:
        if "pg" not in _STATE:
            import pgserver

            root = pathlib.Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / f"a07-spine-pg-{os.getpid()}"
            _STATE["pg"] = pgserver.get_server(str(root), cleanup_mode="delete")
        return _STATE["pg"]


def new_database(prefix: str) -> str:
    name = f"{prefix}_{uuid.uuid4().hex[:10]}"
    server().psql(f"CREATE DATABASE {name};")
    return server().get_uri().replace("/postgres?", f"/{name}?")


def _illustrative() -> dict:
    """01's own fixture listings, read from the pinned commit (never from a peer worktree)."""
    if "fixture" not in _STATE:
        blob = subprocess.run(["git", "show", f"{PIN}:fixtures/sources/illustrative.json"], cwd=QA_ROOT,
                              capture_output=True, check=True).stdout
        _STATE["fixture"] = json.loads(blob)
    return _STATE["fixture"]


def fixture_file(tag: str, ids: list[str], dest: pathlib.Path) -> pathlib.Path:
    """Copy selected listings with unique ids / dedup keys so every call yields new Items."""
    out = []
    for rec in _illustrative()["listings"]:
        if rec["source_listing_id"] in ids:
            rec = json.loads(json.dumps(rec))
            rec["source_listing_id"] = f"{rec['source_listing_id']}-{tag}"
            rec["url"] = f"{rec['url']}?t={tag}"
            rec["record"]["dedup_key"] = f"{rec['record']['dedup_key']}|{tag}"
            out.append(rec)
    dest.mkdir(parents=True, exist_ok=True)
    p = dest / f"fixture-{tag}.json"
    p.write_text(json.dumps({"listings": out}))
    return p


# ------------------------------------------------------------------ the QA facade
class SpineQA:
    implementation = IMPLEMENTATION
    is_mock = False
    pin = PIN

    def __init__(self, workdir: pathlib.Path):
        self.workdir = pathlib.Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            if "rt" not in _STATE:
                from mbos.config import Settings
                from mbos.runtime import Components, init_runtime

                _wrap_effector()
                s = Settings(database_url=new_database("qa_app"), system_database_url=new_database("qa_sys"),
                             approval_poll_seconds=0.3)
                _STATE["rt"] = init_runtime(s, Components())
        self.rt = _STATE["rt"]
        self.engine = self.rt.engine

    # ---------------------------------------------------------------- flow mode (real DBOS workflow)
    def discover(self, listing: str = "FIX-TRAILER-1") -> str:
        from dbos import DBOS, SetWorkflowID

        from mbos import workflows
        from mbos.config import configure
        from mbos.reference.fixture_adapter import FixtureSourceAdapter
        from mbos.runtime import components

        configure(self.rt.settings)
        tag = uuid.uuid4().hex[:8]
        name = f"qa-{tag}"
        components().adapters[name] = FixtureSourceAdapter(fixture_file(tag, [listing], self.workdir), name=name)
        with SetWorkflowID(f"discover:{name}"):
            results = DBOS.start_workflow(workflows.discover, name).get_result()
        (item_id,) = [r["item_id"] for r in results if r["created"]]
        return item_id

    def pending(self, item_id: str, timeout: float = 30) -> dict:
        self.wait_state(item_id, "AWAITING_APPROVAL", timeout)
        return self.scalar("SELECT body FROM mbos.action_requests WHERE item_id = :i AND status IN "
                           "('pending_approval', 'held') ORDER BY body->>'created_at' DESC LIMIT 1", i=item_id)

    def decide(self, areq_id: str, decision: str, *, payload_hash_seen: str | None = None, step_up: bool = True,
               **kw) -> dict:
        from mbos import spine, workflows

        seen = payload_hash_seen or self.areq(areq_id)["payload_hash"]
        try:
            return workflows.record_decision(areq_id, decision, seen, auth_context=STEP_UP if step_up else None, **kw)
        except spine.DecisionRefused as e:
            raise Refused(str(e)) from e
        except Exception as e:  # noqa: BLE001
            # e.g. NO without a reason is refused by the frozen-contract check (ContractViolation), not by
            # DecisionRefused. Same outcome (refused, rolled back), different exception type: finding F-18.
            if type(e).__name__ == "ContractViolation":
                raise Refused(f"ContractViolation: {e}") from e
            raise

    def ping(self, item_id: str) -> None:
        from mbos import workflows

        workflows.ping(item_id)

    def wait_state(self, item_id: str, states, timeout: float = 30) -> str:
        want = {states} if isinstance(states, str) else set(states)
        deadline = time.monotonic() + timeout
        st = None
        while time.monotonic() < deadline:
            st = self.item(item_id)["state"]
            if st in want:
                return st
            time.sleep(0.1)
        raise AssertionError(f"{item_id} stuck in {st}; wanted {sorted(want)}")

    def freeze(self, key: str, frozen: bool) -> None:
        from mbos import spine

        with self.engine.begin() as c:
            spine.set_kill_switch(c, key, frozen, reason="QA drill", actor_id="michael")

    # ---------------------------------------------------------------- reads (any engine)
    def scalar(self, sql: str, engine=None, **p):
        with (engine or self.engine).connect() as c:
            return c.execute(sa.text(sql), p).scalar_one()

    def rows(self, sql: str, engine=None, **p) -> list:
        with (engine or self.engine).connect() as c:
            return list(c.execute(sa.text(sql), p))

    # Reads go through mbos' public API where one exists (ledger.load_item / load_receipts / verify_chain, audit).
    # The raw-SQL reads below (action requests, approvals, effector calls, provenance) have no public reader yet;
    # they are the only lines to re-target when the spine moves onto Agent 04's store (A-01 phase 2).
    def item(self, item_id: str, engine=None) -> dict:
        from mbos.ledger import load_item

        with (engine or self.engine).connect() as c:
            return load_item(c, item_id)

    def areq(self, areq_id: str, engine=None) -> dict:
        return self.scalar("SELECT body FROM mbos.action_requests WHERE action_request_id = :a", engine, a=areq_id)

    def approvals(self, areq_id: str, engine=None) -> list[dict]:
        return [r[0] for r in self.rows("SELECT body FROM mbos.approvals WHERE action_request_id = :a ORDER BY seq",
                                        engine, a=areq_id)]

    def receipts(self, engine=None, **where) -> list[dict]:
        from mbos.ledger import load_receipts

        clause = " AND ".join(f"{k} = :{k}" for k in where) or "true"
        with (engine or self.engine).connect() as c:
            return load_receipts(c, clause, where)

    def effector_rows(self, engine=None, areq_id: str | None = None) -> list[dict]:
        sql = "SELECT idempotency_key, dry_run, response FROM mbos.effector_calls"
        if areq_id:
            sql += " WHERE action_request_id = :a"
        return [dict(r._mapping) for r in self.rows(sql, engine, **({"a": areq_id} if areq_id else {}))]

    def documents(self, engine=None):
        """(contract kind, document) for every stored record, read straight from the tables."""
        for kind, table in (("item", "items"), ("action-request", "action_requests"), ("approval", "approvals"),
                            ("provenance", "provenance"), ("outcome", "outcomes")):
            for (body,) in self.rows(f"SELECT body FROM mbos.{table}", engine):
                yield kind, body
        for r in self.receipts(engine):
            yield "receipt", r

    def find_provenance(self, pid: str, engine=None) -> dict | None:
        r = self.rows("SELECT body FROM mbos.provenance WHERE provenance_id = :p", engine, p=pid)
        return r[0][0] if r else None

    def verify_chain(self, engine=None) -> dict:
        from mbos.ledger import verify_chain

        with (engine or self.engine).connect() as c:
            return verify_chain(c)

    def close(self) -> None:
        """Orderly teardown: stop DBOS (cancelling workflows parked at the approval gate, as 01's own conftest does)
        BEFORE PostgreSQL stops, so nothing polls a dead server."""
        with _LOCK:
            if "rt" not in _STATE:
                return
            from dbos import DBOS

            from mbos.runtime import shutdown

            pending = [w.workflow_id for w in DBOS.list_workflows(status="PENDING", load_input=False, load_output=False)]
            if pending:
                DBOS.cancel_workflows(pending)
                time.sleep(1.0)
            shutdown()
            _STATE.pop("rt")
            if "pg" in _STATE:
                _STATE.pop("pg").cleanup()

    # ---------------------------------------------------------------- ledger mode (fresh DB, plain spine calls)
    def ledger(self) -> "LedgerDB":
        return LedgerDB(self)


class LedgerDB:
    """A fresh migrated database driven by the real `mbos.spine` functions without DBOS (01's own `seed_flow`
    pattern). Destructive tests use this so the shared runtime's chain is never damaged."""

    def __init__(self, qa: SpineQA):
        from mbos.config import configure
        from mbos.db.engine import engine_for
        from mbos.db.migrate import migrate
        from mbos.runtime import Components

        self.qa = qa
        self.url = new_database("qa_ledger")
        from mbos.config import Settings

        configure(Settings(database_url=self.url, system_database_url=self.url))
        self.engine = engine_for(self.url)
        migrate(self.engine)
        configure(qa.rt.settings)  # never leave global settings pointing away from the runtime
        self.comps = Components().with_defaults()

    def seed(self, listing: str = "FIX-TRAILER-1", *, approve: bool = True, act: bool = True, outcome: bool = True) -> dict:
        from mbos import spine
        from mbos.reference.fixture_adapter import FixtureSourceAdapter

        tag = uuid.uuid4().hex[:8]
        raw = FixtureSourceAdapter(fixture_file(tag, [listing], self.qa.workdir), name="fixture").fetch()[0]
        norm = self.comps.normalizer.normalize(raw)
        with self.engine.begin() as c:
            item_id = spine.ingest(c, asdict(raw), asdict(norm), "fixture", "0.1.0", self.comps)["item_id"]
        with self.engine.begin() as c:
            item = spine.read_item(c, item_id)
        with self.engine.begin() as c:
            spine.record_score(c, item_id, asdict(self.comps.scorer.score(item)))
        with self.engine.begin() as c:
            areq_id = spine.route_recommendation(c, item_id, self.comps)["action_request_id"]
        out = {"item_id": item_id, "action_request_id": areq_id}
        if not approve or areq_id is None:
            return out
        h = self.qa.areq(areq_id, self.engine)["payload_hash"]
        with self.engine.begin() as c:
            approval = spine.decide(c, areq_id, "YES", h, self.comps, auth_context=STEP_UP)["approval"]
        out["approval"] = approval
        if not act:
            return out
        with self.engine.begin() as c:
            spine.begin_act(c, item_id, areq_id, approval)
        out["guard"] = self.gateway(areq_id, approval["approval_id"])
        with self.engine.begin() as c:
            spine.finish_act(c, item_id, areq_id, approval, out["guard"])
        if outcome:
            with self.engine.begin() as c:
                spine.record_outcome(c, item_id, "flip_acquired", realized={"total_cost": 825})
        return out

    def gateway(self, areq_id: str, approval_id: str) -> dict:
        return asdict(self.comps.gateway.execute(self.engine, areq_id, approval_id))

    def superuser_sql(self, sql: str, **p) -> None:
        """QA HOOK (superuser): bypasses the application. Used only to tamper or to break things on purpose."""
        with self.engine.begin() as c:
            c.execute(sa.text(sql), p)

    def as_role(self, role: str, sql: str) -> str | None:
        """Run `sql` as a database role inside a rolled-back transaction. Returns the error text, or None if allowed."""
        with self.engine.connect() as c:
            t = c.begin()
            try:
                c.execute(sa.text(f"SET LOCAL ROLE {role}"))
                c.execute(sa.text(sql))
                return None
            except Exception as e:  # noqa: BLE001
                return str(getattr(e, "orig", e)).splitlines()[0]
            finally:
                t.rollback()

    def dispose(self) -> None:
        self.engine.dispose()


# ------------------------------------------------------------------ out-of-process crash / restart (A5, A6)
def child(mode: str, *args: str, urls: tuple[str, str], timeout: float = 120) -> subprocess.CompletedProcess:
    env = {**os.environ, "MBOS_QA_APP_URL": urls[0], "MBOS_QA_SYS_URL": urls[1], "PYTHONPATH": str(QA_ROOT)}
    return subprocess.run([sys.executable, "-m", "mbos_qa._spine_child", mode, *args], cwd=QA_ROOT, env=env,
                          capture_output=True, text=True, timeout=timeout)


def build(workdir, *, mode="mvp", seed=None, clock=None, fresh=True) -> SpineQA:
    """`MBOS_QA_IMPL=mbos_qa.impl_spine:build`. `mode` must stay dry-run; mbos hard-codes DRY_RUN=True."""
    if mode not in ("mvp", "round_one"):
        raise ValueError("the QA lane only runs dry-run modes")
    return SpineQA(pathlib.Path(workdir))
