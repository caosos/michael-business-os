"""D-37 (ADR-0015 P-74-3): registry rows validate against the schema, carry a policy_ref, and per-user interest never leaks."""

import json
from datetime import datetime, timezone

import jsonschema
import psycopg
import pytest
from psycopg import errors

from conftest import make_item
from mbos_state import sources
from test_user_state import _login, _owner

NOW = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)


def test_config_validates_and_every_row_has_policy_ref():
    rows = sources.load_config()
    by = {r["source_id"]: r for r in rows}
    assert all(r["policy_ref"].strip() for r in rows)
    assert by["gsa"]["coverage"]["scope"] == by["ebay"]["coverage"]["scope"] == "national"
    cl = [r for r in rows if r["source_id"].startswith("craigslist_")]
    assert cl and all(r["coverage"]["scope"] == "metro" and r["coverage"]["subdomain"] and r["access_mode"] == "alert_email" for r in cl)
    assert all(by[s]["access_mode"] == "alert_email" for s in ("govdeals", "publicsurplus", "auctionzip"))
    assert all(by[s]["status"] == "blocked" and by[s]["access_mode"] == "manual" for s in ("fb_marketplace", "offerup"))
    assert by["ar_local_auction_houses"]["coverage"]["states"] == ["AR"]
    schema = json.loads((sources.CONFIG_DIR / "sources.schema.json").read_text())
    bad = {"version": "1.0.0", "sources": [{**rows[0], "policy_ref": ""}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
    no_ref = {k: v for k, v in rows[0].items() if k != "policy_ref"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"version": "1.0.0", "sources": [no_ref]}, schema)
    metro_no_center = {**cl[0], "coverage": {"scope": "metro"}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"version": "1.0.0", "sources": [metro_no_center]}, schema)


def test_seed_loader_db_constraints_and_authority(db):
    owner = db.connect("approver")
    n = sources.load_sources(owner)
    assert n == len(sources.load_config())
    assert sources.load_sources(owner) == n  # idempotent
    su = db.connect()
    assert su.execute("SELECT count(*) FROM mbos.source_registry").fetchone()[0] == n
    assert su.execute("SELECT count(*) FROM mbos.source_registry WHERE btrim(policy_ref) = ''").fetchone()[0] == 0
    # DB refuses a row without policy_ref even if the schema were bypassed
    with pytest.raises(errors.CheckViolation):
        owner.execute("SELECT mbos.upsert_source(%s)", (json.dumps({"source_id": "x", "display_name": "X", "coverage": {"scope": "national"},
                                                                    "access_mode": "api", "status": "fixture", "policy_ref": " "}),))
    # only owner_channel writes; no direct table writes; everyone reads
    for role in ("agent_write", "gateway"):
        c = db.connect(role)
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("SELECT mbos.upsert_source(%s)", (json.dumps(sources.load_config()[0]),))
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("UPDATE mbos.source_registry SET status = 'connected'")
    assert db.connect("reader").execute("SELECT count(*) FROM mbos.source_registry").fetchone()[0] == n


def test_user_item_interest_is_private(db):
    sources.load_sources(db.connect("approver"))
    item, _ = make_item(db.store(), "RESEARCHING")
    ann, a = _login(db, "ann")
    bob, b = _login(db, "bob")
    ingest = db.connect("agent_write")
    ingest.execute("SELECT mbos.record_user_item_interest(%s,%s,'craigslist_littlerock',%s)", (ann, item, NOW))
    ingest.execute("SELECT mbos.record_user_item_interest(%s,%s,'craigslist_littlerock',%s)", (ann, item, NOW))  # idempotent
    assert a.execute("SELECT item_id, source_id FROM mbos.get_user_item_interest(%s)", (ann,)).fetchall() == [(item, "craigslist_littlerock")]
    assert b.execute("SELECT * FROM mbos.get_user_item_interest(%s)", (bob,)).fetchall() == []
    for target in (ann, _owner(db)):
        with pytest.raises(errors.InsufficientPrivilege):
            b.execute("SELECT * FROM mbos.get_user_item_interest(%s)", (target,))
    with pytest.raises(errors.InsufficientPrivilege):
        b.execute("SELECT * FROM mbos.user_item_interest")
    with pytest.raises(errors.InsufficientPrivilege):
        db.connect("reader").execute("SELECT mbos.record_user_item_interest(%s,%s,'gsa',%s)", (bob, item, NOW))
    with pytest.raises(errors.ForeignKeyViolation):
        ingest.execute("SELECT mbos.record_user_item_interest(%s,%s,'nope',%s)", (ann, item, NOW))
