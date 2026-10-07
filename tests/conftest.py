"""Test harness (E-02): a throwaway PostgreSQL 16 cluster per session with lane D's canonical schema
(tests/vendor/agent04_state @ 14bd690, migrations 0000–0007, test-only copy), migrated once into a
template; one fresh database per test. Every role connects as its own login over a private unix socket,
so privilege checks are real (gateway / approver / agent_write / policy_admin), not simulated.
"""
from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

from mbos_governance import ActionGateway, PgGovernanceStore, PgPanicStore, PolicyStore
from mbos_governance.ids import fmt_ts, new_id, payload_hash

REPO = Path(__file__).resolve().parents[1]
VENDOR = Path(__file__).resolve().parent / "vendor" / "agent04_state"
TEMPLATE_DB = "mbos05_tpl"
LOGIN = {"superuser": "postgres", "agent_write": "mbos_state_mcp", "gateway": "mbos_gateway",
         "approver": "mbos_operator_ui", "policy_admin": "mbos_policy", "reader": "mbos_reader"}

# Daytime in America/Chicago (outside quiet hours) and in the future relative to the DB clock, so
# lane D's now()-based approval checks and the gateway's injected clock agree.
_tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
NOON = datetime(_tomorrow.year, _tomorrow.month, _tomorrow.day, 15, 0, tzinfo=timezone.utc)

CATEGORY_CAPABILITY = {
    "message": ("comms.message.send", "agent-06-communications"),
    "sms": ("comms.sms.send", "agent-06-communications"),
    "phone_call": ("comms.voice.call", "agent-06-communications"),
    "email": ("comms.email.send", "agent-06-communications"),
    "scheduling": ("schedule.appointment.create", "agent-06-communications"),
    "publishing": ("publish.listing.create", "agent-07-marketing"),
    "offer": ("offer.submit", "agent-01-coordinator"),
    "money": ("money.payment.send", "agent-01-coordinator"),
    "purchase": ("purchase.create", "agent-01-coordinator"),
    "price_change": ("price.change", "agent-01-coordinator"),
    "external_commitment": ("commit.external", "agent-01-coordinator"),
}


def _pg_bin() -> Path:
    if os.environ.get("PG_BIN"):
        return Path(os.environ["PG_BIN"])
    if Path("/usr/lib/postgresql/16/bin/pg_ctl").exists():
        return Path("/usr/lib/postgresql/16/bin")
    import pgserver  # PostgreSQL 16 binaries from the pgserver wheel (no root needed)
    return Path(pgserver.__file__).parent / "pginstall" / "bin"


@pytest.fixture(scope="session")
def cluster():
    pg_bin = _pg_bin()
    root = Path(tempfile.mkdtemp(prefix="mbos05-test-"))
    sock = Path(tempfile.mkdtemp(prefix="m05-", dir=os.environ.get("XDG_RUNTIME_DIR") or "/tmp"))  # <107-byte socket path
    data, port = root / "data", int(os.environ.get("MBOS05_TEST_PORT", "55505"))
    subprocess.run([pg_bin / "initdb", "-D", data, "--auth=trust", "--encoding=UTF8", "--locale=C.UTF-8",
                    "-U", "postgres"], check=True, capture_output=True)
    subprocess.run([pg_bin / "pg_ctl", "-D", data, "-l", root / "pg.log", "-w", "start", "-o",
                    f"-p {port} -k {sock} -c listen_addresses='' -c timezone=UTC -c max_connections=300 -c fsync=off"],
                   check=True, capture_output=True)
    base = f"host={sock} port={port}"
    try:
        with psycopg.connect(f"{base} dbname=postgres user=postgres", autocommit=True) as c:
            c.execute((VENDOR / "bootstrap" / "roles.sql").read_text())
            c.execute(f"CREATE DATABASE {TEMPLATE_DB} OWNER mbos_owner")
        with psycopg.connect(f"{base} dbname={TEMPLATE_DB} user=postgres", autocommit=True) as c:
            c.execute("CREATE SCHEMA dbos AUTHORIZATION mbos_dbos")
        sys.path.insert(0, str(VENDOR))
        try:
            from mbos_state import migrate  # vendored lane D migrator (test-only)
        finally:
            sys.path.remove(str(VENDOR))
        migrate.migrate(f"{base} dbname={TEMPLATE_DB} user=postgres", log=lambda *_: None)
        yield {"base": base}
    finally:
        subprocess.run([pg_bin / "pg_ctl", "-D", data, "-m", "immediate", "-w", "stop"], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(sock, ignore_errors=True)


_counter = itertools.count()


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now = self.now + timedelta(**kw)


class Env:
    def __init__(self, base: str, name: str, tmp: Path):
        self.base, self.name, self.tmp = base, name, tmp
        self.policy_path = tmp / "policy" / "policy.v1.json"
        self.policy_path.parent.mkdir()
        for f in ("policy.v1.json", "policy.schema.json", "content_rules.v1.json"):
            shutil.copy(REPO / "policy" / f, self.policy_path.parent / f)
        self.clock = Clock(NOON)
        self.dsns = {r: self.dsn(r) for r in ("agent_write", "gateway", "approver", "policy_admin")}
        self.store = PgGovernanceStore(self.dsns)
        self.panic = PgPanicStore(self.dsn("gateway"))
        self.gw = ActionGateway(self.store, PolicyStore(self.policy_path), self.panic, clock=self.clock,
                                journal_path=tmp / "panic.journal.jsonl")
        self._agent = psycopg.connect(self.dsn("agent_write"), autocommit=True)
        self.gw.release_panic("L3", None, "michael", "test bootstrap: release initial FROZEN")

    def dsn(self, role: str) -> str:
        return f"{self.base} dbname={self.name} user={LOGIN[role]}"

    def su(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn("superuser"), autocommit=True)

    def sql(self, q: str, params: tuple = (), *, replica: bool = False) -> list:
        """Superuser SQL. replica=True bypasses lane D's triggers: an attacker with DB rights (tamper tests)."""
        with self.su() as c:
            if replica:
                c.execute("SET session_replication_role = replica")
            cur = c.execute(q, params)
            return cur.fetchall() if cur.description else []

    def freeze_sql(self, level: str = "L3", target: str | None = None, reason: str = "out-of-band freeze") -> None:
        """Freeze straight through lane D's API (e.g. another operator process), bypassing this gateway."""
        self.sql("SELECT mbos.panic_set(%s, %s, true, '{\"type\":\"human\",\"id\":\"michael\"}'::jsonb, %s, "
                 "ARRAY[mbos.record_provenance('{\"actor_type\":\"system\",\"basis\":\"FACT\",\"tool_name\":\"test\","
                 "\"tool_version\":\"1\"}'::jsonb)], %s)", (level, target, reason, new_id("ext-freeze")))

    def tamper_payload(self, areq: str, key: str, value) -> None:
        self.sql("UPDATE mbos.action_requests SET payload = payload || %s::jsonb WHERE action_request_id = %s",
                 (json.dumps({key: value}), areq), replica=True)

    def close(self):
        self.store.close()
        self._agent.close()

    # ---- builders (agents write items/provenance through agent_write, like the State MCP) ----
    def provenance(self) -> str:
        return self._agent.execute("SELECT mbos.record_provenance(%s)", (json.dumps({
            "actor_type": "agent", "agent_name": "test", "basis": "INFERENCE", "model_id": "test-model",
            "model_version": "1", "prompt_hash": "sha256:" + "0" * 64}),)).fetchone()[0]

    def item(self) -> str:
        src = self._agent.execute("SELECT mbos.record_provenance(%s)", (json.dumps({
            "actor_type": "external", "basis": "FACT", "source_uri": "https://example.test/listing/1",
            "fetched_at": "2026-10-07T12:00:00Z"}),)).fetchone()[0]
        doc = {"type": "flip", "category": "trailer", "subcategory": "utility trailer 6x12", "dedup_key": new_id("dk"),
               "sources": [{"source": "craigslist", "url": "https://example.test/listing/1", "ingestion_method": "api",
                            "first_seen_at": "2026-10-07T12:00:00Z", "provenance_id": src}],
               "normalized": {"title": "6x12 utility trailer"}}
        return self._agent.execute("SELECT mbos.create_item(%s,%s,%s,%s,%s)", (
            json.dumps(doc), json.dumps({"type": "agent", "id": "agent-02-opportunity"}), "ingest", [src],
            new_id("ci"))).fetchone()[0]

    def ar(self, category: str = "email", **over) -> dict:
        cap, agent = CATEGORY_CAPABILITY[category]
        payload = over.pop("payload", {"to_ref": "relay:EXAMPLE-0001", "template_id": "t1", "n": new_id("x")})
        reversibility = over.pop("reversibility", "reversible")
        body = {
            "action_request_id": new_id("areq"),
            "item_id": self.item(),
            "created_at": fmt_ts(self.clock()),
            "proposed_by": agent,
            "on_behalf_of": "michael",
            "capability": cap,
            "category": category,
            "payload": payload,
            "payload_hash": payload_hash(payload),
            "idempotency_key": new_id("idem"),
            "reversibility": reversibility,
            "tier": 0,
            "status": "drafted",
            "expires_at": fmt_ts(self.clock() + timedelta(hours=48)),
            "provenance_ids": [self.provenance()],
        }
        if category in ("offer", "money", "purchase", "external_commitment"):
            body["estimated_cost"] = {"amount": 100, "currency": "USD"}
        body.update(over)
        return body

    def approval(self, ar: dict, decision: str = "YES", **over) -> dict:
        body = {
            "approval_id": new_id("appr"),
            "action_request_id": ar["action_request_id"],
            "decision": decision,
            "decider": "michael",
            "decided_at": fmt_ts(self.clock()),
            "channel": "web",
            "auth_context": {"method": "webauthn", "step_up": True},
            "payload_hash_seen": ar["payload_hash"],
            "scope": "once",
        }
        if decision == "NO":
            body["reason"] = "not interested"
        if decision == "HOLD":
            body["hold"] = {"hold_until": fmt_ts(self.clock() + timedelta(hours=12)), "wake_on": ["time"]}
        if decision == "MODIFY":
            body["modifications"] = {"diff": {"n": "changed"}, "new_action_request_id": new_id("areq"),
                                     "new_payload_hash": "sha256:" + "1" * 64}
        body.update(over)
        return body

    def propose(self, category: str = "email", **over) -> dict:
        ar = self.ar(category, **over)
        res = self.gw.propose(ar, ar["proposed_by"])
        assert res.outcome == "pending_approval", res
        return ar

    def approved(self, category: str = "email", **over) -> dict:
        ar = self.propose(category, **over)
        res = self.gw.record_approval(self.approval(ar))
        assert res.status == "approved" and not res.reasons, res
        return ar

    def status(self, areq: str) -> str:
        return self.store.action_request(areq)["status"]

    def policy_edit(self, fn) -> None:
        data = json.loads(self.policy_path.read_text())
        fn(data)
        self.policy_path.write_text(json.dumps(data))
        st = self.policy_path.stat()  # guarantee the reload stamp changes
        os.utime(self.policy_path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


@pytest.fixture
def env(cluster, tmp_path):
    name = f"t05_{os.getpid()}_{next(_counter)}"
    with psycopg.connect(f"{cluster['base']} dbname=postgres user=postgres", autocommit=True) as c:
        c.execute(f"CREATE DATABASE {name} TEMPLATE {TEMPLATE_DB} OWNER mbos_owner")
    e = Env(cluster["base"], name, tmp_path)
    yield e
    e.close()
    with psycopg.connect(f"{cluster['base']} dbname=postgres user=postgres", autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
