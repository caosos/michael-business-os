"""A10 contract conformance against the vendored frozen schemas, ID format, and migration hygiene."""

import json
import shutil
from pathlib import Path

import psycopg
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from mbos_state import ids, migrate
from conftest import GATEWAY, MICHAEL, TEMPLATE_DB, key, make_areq, make_item, payload_hash, to_pending

CONTRACTS = Path(__file__).parent / "contracts-v1.0.0"


@pytest.fixture(scope="module")
def validators():
    schemas = {}
    for p in list(CONTRACTS.glob("*.schema.json")) + list(CONTRACTS.glob("vendor/agent-03/*.schema.json")):
        schemas[p.name] = json.loads(p.read_text())
    reg = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas.values()])
    return {name.removesuffix(".schema.json"): Draft202012Validator(s, registry=reg) for name, s in schemas.items()}


def _errors(v, doc):
    return [f"{list(e.absolute_path)}: {e.message[:160]}" for e in v.iter_errors(doc)]


def test_stored_records_conform_to_frozen_contracts(db, validators):
    s = db.store()
    item_id, pid = make_item(s, "AWAITING_APPROVAL")
    areq = make_areq(s, item_id, pid)
    to_pending(s, areq, pid)
    s.record_approval({"action_request_id": areq, "decision": "HOLD", "decider": "michael", "channel": "web",
                       "payload_hash_seen": payload_hash(s, areq), "scope": "once",
                       "hold": {"hold_until": "2026-10-09T00:00:00Z", "wake_on": ["time"]}}, MICHAEL, "HOLD", key())
    s.record_outcome({"item_id": item_id, "kind": "flip_passed_missed", "provenance_ids": [pid],
                      "realized": {"net_profit": 0}}, GATEWAY, "missed", key())
    checks = {
        "receipt": "SELECT doc FROM mbos.v_receipt_documents",
        "provenance": "SELECT doc FROM mbos.v_provenance_documents",
        "action-request": "SELECT doc FROM mbos.v_action_request_documents",
        "approval": "SELECT doc FROM mbos.v_approval_documents",
        "outcome": "SELECT doc FROM mbos.v_outcome_documents",
    }
    seen = 0
    for contract, sql in checks.items():
        for (doc,) in s.conn.execute(sql):
            assert not _errors(validators[contract], doc), (contract, doc, _errors(validators[contract], doc))
            seen += 1
    assert seen > 15


def test_item_document_envelope_conforms(db, validators):
    """The item envelope written by the State API conforms; nested economics/scores belong to 02/03 content."""
    s = db.store()
    item_id, _ = make_item(s, "NORMALIZED")
    doc = s.item_document(item_id)
    errs = _errors(validators["item"], doc)
    assert not errs, errs


def test_contract_examples_load_into_db(db, validators):
    """The frozen provenance example is accepted by the DB constraints."""
    s = db.store()
    ex = json.loads((CONTRACTS / "examples" / "provenance-human.example.json").read_text())
    ex.pop("approval_id", None)  # its approval does not exist in this DB (FK); resolve via tool instead
    ex.update(tool_name="example", tool_version="1")
    pid = s.record_provenance(**ex)
    assert pid == ex["provenance_id"]


def test_ids_python_and_sql_agree(db):
    s = db.store()
    for prefix in ids.PREFIXES:
        sql_id = s.conn.execute("SELECT mbos.new_id(%s)", (prefix,)).fetchone()[0]
        assert ids.is_id(sql_id, prefix) and ids.is_id(ids.new_id(prefix), prefix)
    a, b = ids.ulid(1_000), ids.ulid(2_000)
    assert a[:10] < b[:10]  # time-ordered prefix


def test_every_migration_is_receipted(db):
    s = db.store()
    rows = s.conn.execute("""SELECT m.version, r.type, r.inputs_hash = m.sha256
                             FROM mbos_meta.schema_migrations m JOIN mbos.receipts r USING (receipt_id)
                             ORDER BY m.version""").fetchall()
    assert [r[0] for r in rows] == [m.version for m in migrate.discover()]
    assert all(t == "CONFIG_VERSION_BUMPED" and same for _, t, same in rows)


def test_migrate_is_idempotent_and_detects_drift(db, tmp_path):
    assert migrate.migrate(db.dsn("superuser"), log=lambda *_: None) == []
    copy = tmp_path / "migrations"
    shutil.copytree(migrate.MIGRATIONS_DIR, copy)
    p = copy / "0001_foundation.sql"
    p.write_text(p.read_text() + "\n-- edited after apply\n")
    with pytest.raises(migrate.MigrationDrift):
        migrate.migrate(db.dsn("superuser"), copy, log=lambda *_: None)
