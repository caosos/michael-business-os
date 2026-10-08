"""REAL implementation under test: Agent 01's spine (`mbos`), installed from a pinned commit (`qa/impl_spine_PIN`),
on PostgreSQL 16 (pgserver). Tasks G-02 / G-04, `MBOS_QA_IMPL=mbos_qa.impl_spine:build`.

Nothing in this module re-implements the product. Every state change, decision, guard check and receipt is
produced by `mbos.workflows` / `mbos.spine[_d]` / `mbos.ledger` / lane D / lane E. This adapter only:
  * starts PostgreSQL, launches the real DBOS runtime once per process, and makes fresh migrated databases;
  * feeds 01's own fixture listings through the real `workflows.discover` (unique per call);
  * reads state back, and counts effector *invocations* by wrapping (not replacing) the effector;
  * provides superuser-only fault and tamper hooks that the acceptance tests need (labelled as such).

Configuration (env), both default to the G-02 setup:
  * MBOS_QA_STATE_BACKEND = reference | lane_d     (`mbos.config.Settings.state_backend`)
  * MBOS_QA_GATEWAY_MODE  = reference | lane_e     (`Settings.gateway_mode`; lane_e requires lane_d)
G-04 (wave-two release candidate) = lane_d + lane_e: Agent 04's canonical schema at the head pinned in
`impl_lane_pins.json`, Agent 05's real ActionGateway / PANIC / PDP from its own archive, and its whole `policy/` dir.

Two modes:
  * flow: the shared, launched DBOS runtime (decisions → durable approval gate → gateway → receipts).
  * `ledger()`: a fresh migrated database with no DBOS, seeded through the real spine functions, used for
    destructive tests (tamper, mutation, fault injection) so they never damage the shared chain.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from dataclasses import asdict
from typing import Any

QA_ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = QA_ROOT.parent
PIN = (QA_ROOT / "impl_spine_PIN").read_text().strip()
LANE_PINS = json.loads((QA_ROOT / "impl_lane_pins.json").read_text())
# F-16 is fixed (A-10): the non-editable install ships its contracts and operator profile; no env override.

import sqlalchemy as sa  # noqa: E402

from . import pincheck  # noqa: E402

pincheck.require()  # never test stale code (pip keeps an old copy when the version string is unchanged)

STEP_UP = {"method": "qa_step_up", "step_up": True}
STATE_BACKEND = os.environ.get("MBOS_QA_STATE_BACKEND", "reference")
GATEWAY_MODE = os.environ.get("MBOS_QA_GATEWAY_MODE", "reference")
LANE_D = STATE_BACKEND == "lane_d"
LANE_E = GATEWAY_MODE == "lane_e"
if LANE_E and not LANE_D:
    raise RuntimeError("gateway_mode=lane_e requires state_backend=lane_d")
IMPLEMENTATION = (f"REAL: Agent 01 spine `mbos` @ {PIN[:7]}, state_backend=`{STATE_BACKEND}`"
                  + (f" (Agent 04 schema @ {LANE_PINS['lane_d_04'][:7]})" if LANE_D else "")
                  + f", gateway_mode=`{GATEWAY_MODE}`"
                  + (f" (Agent 05 gateway @ {LANE_PINS['lane_e_05'][:7]})" if LANE_E else "")
                  + ", on PostgreSQL 16 (pgserver) + DBOS")


class Refused(Exception):
    """The implementation refused a decision (normalises `mbos.spine.DecisionRefused`)."""


# ------------------------------------------------------------------ process-wide resources
_LOCK = threading.RLock()
_STATE: dict[str, Any] = {}
INVOCATIONS: dict[str, int] = {}  # idempotency_key → number of effector executions in THIS process


def _effector_target():
    if LANE_E:
        import mbos_governance.effectors as e

        return e.DryRunEffector, "_execute", (lambda args: args[0].idempotency_key)  # (token, action_request)
    import mbos.reference.governance as g

    return g.DryRunEffector, "execute", (lambda args: args[1]["idempotency_key"])  # (engine, action_request)


def _wrap_effector() -> None:
    """Count effector *executions* by wrapping the effector class in use (never replacing its behaviour)."""
    cls, name, key_of = _effector_target()
    original = getattr(cls, name)
    if getattr(original, "_qa_wrapped", False):
        return

    def counted(self, *args, **kw):
        k = key_of(args)
        INVOCATIONS[k] = INVOCATIONS.get(k, 0) + 1
        return original(self, *args, **kw)

    counted._qa_wrapped = True
    setattr(cls, name, counted)


def _install_crash(point: str) -> None:
    """Hard process death (os._exit) inside the gateway's effector call — before or after it happened."""
    cls, name, _ = _effector_target()
    inner = getattr(cls, name)

    def crashing(self, *args, **kw):
        if point == "before_effector":
            print("CRASH before_effector", flush=True)
            os._exit(137)
        resp = inner(self, *args, **kw)  # the effector call is recorded …
        print("CRASH after_effector", flush=True)
        os._exit(137)  # … but the process dies before the gateway step is checkpointed
        return resp

    setattr(cls, name, crashing)


def server():
    with _LOCK:
        if "pg" not in _STATE:
            import pgserver

            from . import pgdir

            root = pgdir.make("spine-")  # on disk, short path; removed in close()/atexit, swept if we are killed
            _STATE["pg_dir"] = root
            _STATE["pg"] = pgserver.get_server(str(root), cleanup_mode="stop")
        return _STATE["pg"]


def _db_url(name: str) -> str:
    return server().get_uri().replace("/postgres?", f"/{name}?")


def new_database(prefix: str) -> str:
    name = f"{prefix}_{uuid.uuid4().hex[:10]}"
    server().psql(f"CREATE DATABASE {name};")
    return _db_url(name)


def _archive(ref: str, dest: pathlib.Path, *paths: str) -> None:
    tar = subprocess.run(["git", "archive", ref, *paths], cwd=REPO, capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(dest, filter="data")


def lane_d_src(pin: str = "lane_d_04") -> pathlib.Path:
    """Agent 04's `state/` at the pinned head (read-only `git archive`; never merged). `pin` selects the key in impl_lane_pins.json
    (G-16 uses `lane_d_04_numbers`: the head with the capital ledger, 0017/0018)."""
    with _LOCK:
        if "lane_d_src:" + pin not in _STATE:
            d = pathlib.Path(tempfile.mkdtemp(prefix="a07-lane-d-"))
            _archive(LANE_PINS[pin], d, "state")
            _STATE["lane_d_src:" + pin] = d
        return _STATE["lane_d_src:" + pin]


def policy_path() -> str:
    """Agent 05's WHOLE `policy/` dir (policy + schema + content rules each fail closed if missing)."""
    with _LOCK:
        if "policy" not in _STATE:
            d = pathlib.Path(tempfile.mkdtemp(prefix="a07-policy-"))
            _archive(LANE_PINS["lane_e_05"], d, "policy")
            _STATE["policy"] = d / "policy" / "policy.v1.json"
        return str(_STATE["policy"])


def new_lane_d_database(prefix: str = "qa_d", pin: str = "lane_d_04") -> str:
    """roles.sql (idempotent per cluster) + CREATE DATABASE + pgvector + lane D's own migrator. Mirrors 01's recipe
    (`tests/helpers/lane_d.py`) and lane D's `bootstrap.sh`; the app connects as the owner, as 01's tests do."""
    import importlib

    import psycopg

    src = lane_d_src(pin)
    srv = server()
    name = f"{prefix}_{uuid.uuid4().hex[:10]}"
    with _LOCK:
        srv.psql((src / "state/bootstrap/roles.sql").read_text())
        srv.psql(f"CREATE DATABASE {name} OWNER mbos_owner;")
    url = _db_url(name)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("CREATE SCHEMA IF NOT EXISTS mbos_ext")
        c.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA mbos_ext")
        c.execute("GRANT USAGE ON SCHEMA mbos_ext TO agent_read, agent_write, gateway, approver, policy_admin, mbos_owner")
    with _LOCK:
        sys.path.insert(0, str(src / "state"))
        try:
            importlib.import_module("mbos_state.migrate").migrate(url, log=lambda *_: None)
        finally:
            sys.path.remove(str(src / "state"))
            for m in [m for m in sys.modules if m.startswith("mbos_state")]:
                del sys.modules[m]
    return url


def boot_runtime(app_url: str, sys_url: str, *, crash_at: str | None = None):
    """Launch the real runtime for the configured backend. Used by this process and by crash/restart children."""
    from mbos.config import Settings
    from mbos.runtime import Components, init_runtime

    comps = Components()
    s = Settings(database_url=app_url, system_database_url=sys_url, approval_poll_seconds=0.3,
                 state_backend=STATE_BACKEND, gateway_mode=GATEWAY_MODE)
    if LANE_E:
        from mbos.adapters.governance import lane_e_components

        comps, _gov = lane_e_components(s.database_url, os.environ.get("MBOS_POLICY_PATH") or policy_path())
    _wrap_effector()
    if crash_at:
        _install_crash(crash_at)
    rt = init_runtime(s, comps)
    assert rt.settings.state_backend == STATE_BACKEND and rt.settings.gateway_mode == GATEWAY_MODE
    if LANE_D:  # a fresh lane D database is FROZEN; Michael (approver/owner) releases it, receipted
        from mbos import spine_d

        with rt.engine.begin() as c:
            spine_d.set_kill_switch(c, "global_freeze", False, reason="QA bootstrap: Michael releases the initial FROZEN state")
    return rt


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


# ------------------------------------------------------------------ document access (backend-neutral)
# kind → (reference table, reference col, lane-D view, pk)
_DOCS = {
    "item": ("items", "body", "v_item_documents", "item_id"),
    "action-request": ("action_requests", "body", "v_action_request_documents", "action_request_id"),
    "approval": ("approvals", "body", "v_approval_documents", "approval_id"),
    "provenance": ("provenance", "body", "v_provenance_documents", "provenance_id"),
    "outcome": ("outcomes", "body", "v_outcome_documents", "outcome_id"),
}


def spine_module():
    from mbos.runtime import spine_module as sm

    return sm()


# ------------------------------------------------------------------ the QA facade
class SpineQA:
    implementation = IMPLEMENTATION
    is_mock = False
    pin = PIN
    lane_d = LANE_D
    lane_e = LANE_E

    def __init__(self, workdir: pathlib.Path):
        self.workdir = pathlib.Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            if "rt" not in _STATE:
                app = new_lane_d_database("qa_app") if LANE_D else new_database("qa_app")
                _STATE["rt"] = boot_runtime(app, new_database("qa_sys"))
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
        return self.areqs(item_id=item_id, status=("pending_approval", "held"))[-1]

    def decide(self, areq_id: str, decision: str, *, payload_hash_seen: str | None = None, step_up: bool = True,
               **kw) -> dict:
        from mbos import spine, workflows

        seen = payload_hash_seen or self.areq(areq_id)["payload_hash"]
        try:
            return workflows.record_decision(areq_id, decision, seen, auth_context=STEP_UP if step_up else None, **kw)
        except spine.DecisionRefused as e:
            raise Refused(str(e)) from e

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
        with self.engine.begin() as c:
            spine_module().set_kill_switch(c, key, frozen, reason="QA drill", actor_id="michael")

    # ---------------------------------------------------------------- reads (any engine)
    def scalar(self, sql: str, engine=None, **p):
        with (engine or self.engine).connect() as c:
            return c.execute(sa.text(sql), p).scalar_one()

    def rows(self, sql: str, engine=None, **p) -> list:
        with (engine or self.engine).connect() as c:
            return list(c.execute(sa.text(sql), p))

    def _select(self, kind: str) -> tuple[str, str]:
        table, col, view, _pk = _DOCS[kind]
        return (f"mbos.{view}", "doc") if LANE_D else (f"mbos.{table}", col)

    def _doc(self, kind: str, key: str, engine=None) -> dict:
        frm, col = self._select(kind)
        return self.scalar(f"SELECT {col} FROM {frm} WHERE {_DOCS[kind][3]} = :k", engine, k=key)

    def item(self, item_id: str, engine=None) -> dict:
        return self._doc("item", item_id, engine)

    def areq(self, areq_id: str, engine=None) -> dict:
        return self._doc("action-request", areq_id, engine)

    def areqs(self, engine=None, *, item_id: str | None = None, status=None) -> list[dict]:
        frm, col = self._select("action-request")
        where, p = ["true"], {}
        if item_id:
            where.append(f"{col}->>'item_id' = :i")
            p["i"] = item_id
        if status:
            where.append(f"{col}->>'status' = ANY(:s)")
            p["s"] = [status] if isinstance(status, str) else list(status)
        return [r[0] for r in self.rows(
            f"SELECT {col} FROM {frm} WHERE {' AND '.join(where)} ORDER BY {col}->>'created_at'", engine, **p)]

    def approvals(self, areq_id: str, engine=None) -> list[dict]:
        frm, col = self._select("approval")
        order = f"{col}->>'decided_at', {col}->>'approval_id'" if LANE_D else "seq"
        return [r[0] for r in self.rows(
            f"SELECT {col} FROM {frm} WHERE {col}->>'action_request_id' = :a ORDER BY {order}", engine, a=areq_id)]

    def receipts(self, engine=None, **where) -> list[dict]:
        if LANE_D:
            clause = " AND ".join(f"doc->>'{k}' = :{k}" for k in where) or "true"
            return [r[0] for r in self.rows(f"SELECT doc FROM mbos.v_receipt_documents WHERE {clause} ORDER BY seq",
                                            engine, **where)]
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
        """(contract kind, document) for every stored record, as the backend exposes them."""
        for kind in _DOCS:
            frm, col = self._select(kind)
            for (body,) in self.rows(f"SELECT {col} FROM {frm}", engine):
                yield kind, body
        for r in self.receipts(engine):
            yield "receipt", r

    def find_provenance(self, pid: str, engine=None) -> dict | None:
        frm, col = self._select("provenance")
        r = self.rows(f"SELECT {col} FROM {frm} WHERE provenance_id = :p", engine, p=pid)
        return r[0][0] if r else None

    def verify_chain(self, engine=None) -> dict:
        with (engine or self.engine).connect() as c:
            if LANE_D:
                from mbos.adapters.state04 import Pg04Ledger

                return Pg04Ledger().verify_chain(c)
            from mbos.ledger import verify_chain

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
            if "pg_dir" in _STATE:
                from . import pgdir

                pgdir.release(_STATE.pop("pg_dir"))

    # ---------------------------------------------------------------- ledger mode (fresh DB, plain spine calls)
    def ledger(self) -> "LedgerDB":
        return LedgerDB(self)


class LedgerDB:
    """A fresh migrated database driven by the real spine functions without DBOS (01's own `seed_flow` pattern).
    Destructive tests use this so the shared runtime's chain is never damaged."""

    def __init__(self, qa: SpineQA):
        from mbos.config import Settings, configure
        from mbos.db.engine import engine_for
        from mbos.db.migrate import migrate
        from mbos.runtime import Components

        self.qa = qa
        if LANE_D:
            self.url = new_lane_d_database("qa_ledger")
            self.settings = Settings(database_url=self.url, system_database_url=self.url,
                                     state_backend=STATE_BACKEND, gateway_mode=GATEWAY_MODE)
            configure(self.settings)
            self.engine = engine_for(self.url)
            if LANE_E:
                from mbos.adapters.governance import lane_e_components

                self.comps, self.gov = lane_e_components(self.url, policy_path())
                self.comps = self.comps.with_defaults("lane_d")
            else:
                self.comps = Components().with_defaults("lane_d")
            self.panic("L3", None, engage=False, reason="QA bootstrap: Michael releases the initial FROZEN state")
        else:
            self.url = new_database("qa_ledger")
            self.settings = Settings(database_url=self.url, system_database_url=self.url)
            configure(self.settings)
            self.engine = engine_for(self.url)
            migrate(self.engine)
            self.comps = Components().with_defaults()
        configure(qa.rt.settings)  # never leave global settings pointing away from the runtime

    def panic(self, level: str, target: str | None, *, engage: bool, reason: str = "QA drill") -> None:
        """Engage/release PANIC on THIS ledger database. On the lane E stack `spine_d.set_kill_switch` goes through the
        SHARED runtime's governance object (A-18), so a fresh ledger DB must use its own `self.gov`."""
        if LANE_E:
            from mbos_governance import spine_adapter as gov_sa

            fn = gov_sa.engage_panic if engage else gov_sa.release_panic
            out = fn(self.gov, level, target, "michael", reason)
            if isinstance(out, dict) and out.get("error"):
                raise RuntimeError(f"PANIC {'engage' if engage else 'release'} {level} failed: {out['error']}")
            return
        from mbos import spine_d

        key = "global_freeze" if level == "L3" else (f"capability_freeze:{target}" if level == "L2" else f"agent_freeze:{target}")
        with self.engine.begin() as c:
            spine_d.set_kill_switch(c, key, engage, reason=reason)

    def _use(self):
        from mbos.config import configure

        configure(self.settings)
        if LANE_D:
            from mbos import spine_d

            return spine_d
        from mbos import spine

        return spine

    def seed(self, listing: str = "FIX-TRAILER-1", *, approve: bool = True, act: bool = True, outcome: bool = True) -> dict:
        from mbos.reference.fixture_adapter import FixtureSourceAdapter

        spine = self._use()
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
        self._use()
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

    # ---- backend-neutral hooks used by the spec tests (each maps onto the real API / schema of the backend) ----
    def transition(self, conn, item_id: str, to_state: str, provenance_ids: list[str]) -> None:
        """One item transition + its receipt through the backend's own public API."""
        if LANE_D:
            from mbos.adapters.state04 import Pg04Ledger

            Pg04Ledger().transition_item(conn, item_id, to_state, {"type": "system", "id": "qa"}, "qa transition",
                                         provenance_ids, f"qa:{item_id}:{to_state}:{uuid.uuid4().hex[:8]}")
        else:
            from mbos import ledger

            ledger.transition_item(conn, item_id, to_state, intent="qa transition", provenance_ids=provenance_ids)

    def force_state(self, item_id: str, state: str) -> None:
        """QA HOOK (owner): write an item state straight into the table, bypassing the application."""
        if LANE_D:
            self.superuser_sql("UPDATE mbos.items SET state = :s WHERE item_id = :i", s=state, i=item_id)
        else:
            self.superuser_sql("UPDATE mbos.items SET body = jsonb_set(body, '{state}', to_jsonb(CAST(:s AS text))) "
                               "WHERE item_id = :i", s=state, i=item_id)

    def tamper_receipt(self, seq: int, field: str, value) -> None:
        """QA HOOK (owner, user triggers disabled): rewrite one receipt field in place."""
        self.superuser_sql("ALTER TABLE mbos.receipts DISABLE TRIGGER USER")
        try:
            if LANE_D:
                if field == "intent":
                    self.superuser_sql("UPDATE mbos.receipts SET intent = :v WHERE seq = :s", v=value, s=seq)
                else:  # effector_response.dry_run
                    self.superuser_sql("UPDATE mbos.receipts SET effector_response = jsonb_set(effector_response, "
                                       "'{dry_run}', to_jsonb(CAST(:v AS boolean))) WHERE seq = :s", v=value, s=seq)
            else:
                body = self.qa.scalar("SELECT body FROM mbos.receipts WHERE seq = :s", self.engine, s=seq)
                if field == "intent":
                    body["intent"] = value
                else:
                    body["effector_response"]["dry_run"] = value
                self.superuser_sql("UPDATE mbos.receipts SET body = CAST(:b AS jsonb) WHERE seq = :s",
                                   b=json.dumps(body), s=seq)
        finally:
            self.superuser_sql("ALTER TABLE mbos.receipts ENABLE TRIGGER USER")

    def break_kill_switch(self, how: str) -> None:
        """QA HOOK (owner): damage the PANIC state the gateway reads, to prove it fails closed."""
        if LANE_E:  # lane E reads `mbos.panic_read()` over lane D's sealed `mbos.panic_state`
            if how == "L3 frozen":
                self.panic("L3", None, engage=True)
            elif how == "state emptied":
                self.superuser_sql("ALTER TABLE mbos.panic_state DISABLE TRIGGER USER")
                self.superuser_sql("DELETE FROM mbos.panic_state")
            elif how == "checksum corrupted":
                self.superuser_sql("ALTER TABLE mbos.panic_state DISABLE TRIGGER USER")
                self.superuser_sql("UPDATE mbos.panic_state SET body = jsonb_set(body, '{checksum}', '\"tampered\"')")
            elif how == "reader unavailable":
                self.superuser_sql("ALTER FUNCTION mbos.panic_read() RENAME TO panic_read_gone")
            else:
                raise KeyError(how)
        else:
            sql = {
                "L3 frozen": "UPDATE mbos.governance_flags SET value = '{\"frozen\": true}' WHERE key = 'global_freeze'",
                "state emptied": "DELETE FROM mbos.governance_flags WHERE key = 'global_freeze'",
                "checksum corrupted": "UPDATE mbos.governance_flags SET value = '{\"frozen\": \"no\"}' WHERE key = 'global_freeze'",
                "reader unavailable": "ALTER TABLE mbos.governance_flags RENAME TO governance_flags_gone",
            }[how]
            self.superuser_sql(sql)

    def repair_kill_switch(self) -> None:
        """QA HOOK (owner): undo `break_kill_switch("reader unavailable")` — the switch becomes readable again."""
        if LANE_E:
            self.superuser_sql("ALTER FUNCTION mbos.panic_read_gone() RENAME TO panic_read")
        else:
            self.superuser_sql("ALTER TABLE mbos.governance_flags_gone RENAME TO governance_flags")

    def freeze_scoped(self, level: str, target: str) -> None:
        key = f"capability_freeze:{target}" if level == "L2" else f"agent_freeze:{target}"
        if LANE_D:
            self.panic(level, target, engage=True)
        else:
            self.superuser_sql("INSERT INTO mbos.governance_flags (key, value) VALUES (:k, '{\"frozen\": true}')", k=key)

    def dispose(self) -> None:
        self.engine.dispose()


# ------------------------------------------------------------------ out-of-process crash / restart (A5, A6)
def child(mode: str, *args: str, urls: tuple[str, str], timeout: float = 150) -> subprocess.CompletedProcess:
    env = {**os.environ, "MBOS_QA_APP_URL": urls[0], "MBOS_QA_SYS_URL": urls[1], "PYTHONPATH": str(QA_ROOT),
           "MBOS_QA_STATE_BACKEND": STATE_BACKEND, "MBOS_QA_GATEWAY_MODE": GATEWAY_MODE}
    if LANE_E:
        env["MBOS_POLICY_PATH"] = policy_path()
    return subprocess.run([sys.executable, "-m", "mbos_qa._spine_child", mode, *args], cwd=QA_ROOT, env=env,
                          capture_output=True, text=True, timeout=timeout)


def new_runtime_databases(prefix: str) -> tuple[str, str]:
    return (new_lane_d_database(f"{prefix}_app") if LANE_D else new_database(f"{prefix}_app"),
            new_database(f"{prefix}_sys"))


def build(workdir, *, mode="mvp", seed=None, clock=None, fresh=True) -> SpineQA:
    """`MBOS_QA_IMPL=mbos_qa.impl_spine:build`. `mode` must stay dry-run; mbos hard-codes DRY_RUN=True."""
    if mode not in ("mvp", "round_one"):
        raise ValueError("the QA lane only runs dry-run modes")
    return SpineQA(pathlib.Path(workdir))
