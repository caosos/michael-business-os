"""B-40: per-user alert-mail ingest; fixtures only, read-only."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from conftest import FIX
from mbos_discovery.adapters import EmlDirReader
from mbos_discovery.peruser_alerts import ingest

HANDLES = {"alice": "user-alice", "bob": "user-bob"}
NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)
DATA = Path(__file__).resolve().parents[1] / "src/mbos_discovery/data"


def _run():
    return ingest(EmlDirReader(FIX / "peruser_mail"), HANDLES, clock=lambda: NOW)


def test_registry_copy_matches_pinned_d38_hash():
    pinned = (DATA / "PINNED.md").read_text()
    assert "b0cb55e" in pinned
    want = re.search(r"sources\.v1\.json.*?sha256 ([0-9a-f]{64})", pinned, re.S).group(1)
    assert hashlib.sha256((DATA / "sources.v1.json").read_bytes()).hexdigest() == want
    json.loads((DATA / "sources.v1.json").read_text())


def test_two_users_get_disjoint_feeds():
    r = _run()
    a = {i.listing_id for i, _ in r.feed("user-alice")}
    b = {i.listing_id for i, _ in r.feed("user-bob")}
    assert a == {"7720000001", "7720000002"} and b == {"7720000002", "7720000003"}
    assert a & b == {"7720000002"}      # only a posting both really received overlaps
    assert not ({"7720000004", "7720000005", "7720000006"} & (a | b))


def test_shared_fact_stored_once_with_two_interest_rows():
    r = _run()
    assert len([k for k in r.facts if k[1] == "7720000002"]) == 1
    assert len([i for i in r.interests if i.listing_id == "7720000002"]) == 2
    assert r.facts[("craigslist_email", "7720000001")].title == "Utility trailer 5x10"


def test_untagged_unknown_and_spoofed_quarantined_owner_only():
    r = _run()
    assert sorted(q.reason.split(":")[0] for q in r.quarantine) == [
        "no plus tag", "unauthenticated or unparsable", "unknown plus tag"]
    assert r.quarantine_view(False) == [] and len(r.quarantine_view(True)) == 3
    assert next(q for q in r.quarantine if q.to_tag == "mallory").reason == "unknown plus tag"


def test_alert_state_per_user():
    r = _run()
    assert set(r.alert_state) == {("user-alice", "craigslist_email"), ("user-bob", "craigslist_email")}

