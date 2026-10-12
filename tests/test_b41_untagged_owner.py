"""B-41: untagged authenticated alerts go to the owner when configured; base_local comes from config."""
from __future__ import annotations

import tomllib
from datetime import datetime, timezone
from pathlib import Path

from conftest import FIX
from mbos_discovery.adapters import EmlDirReader
from mbos_discovery.peruser_alerts import ingest, ingest_from_config

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)
HANDLES = {"alice": "user-alice", "bob": "user-bob"}
EXAMPLE = Path(__file__).resolve().parents[1] / "config/discovery.example.toml"


def _run(**kw):
    return ingest(EmlDirReader(FIX / "peruser_mail"), HANDLES, clock=lambda: NOW, **kw)


def test_untagged_authenticated_goes_to_owner_when_set():
    r = _run(untagged_user="owner")
    assert r.feed("owner") and all(i.user_id == "owner" for i, _ in r.feed("owner"))
    reasons = sorted(q.reason.split(":")[0] for q in r.quarantine)
    assert reasons == ["unauthenticated or unparsable", "unknown plus tag"]   # spoof + mallory still held
    assert {i.listing_id for i, _ in r.feed("user-alice")} == {"7720000001", "7720000002"}


def test_untagged_quarantined_when_not_set():
    r = _run()
    assert r.feed("owner") == [] and "no plus tag" in [q.reason for q in r.quarantine]


def test_base_local_from_config(tmp_path):
    for p in (FIX / "peruser_mail").glob("*.eml"):
        (tmp_path / p.name).write_bytes(p.read_bytes().replace(b"alerts", b"dealsniffer2026", 1))
    cfg = tomllib.loads(EXAMPLE.read_text())["peruser_alerts"]
    assert cfg["base_local"] == "dealsniffer2026"
    cfg = {**cfg, "handles": HANDLES}
    r = ingest_from_config(EmlDirReader(tmp_path), cfg, clock=lambda: NOW)
    assert {i.listing_id for i, _ in r.feed("user-alice")} == {"7720000001", "7720000002"}
    assert r.feed("owner")                                # untagged to dealsniffer2026@ -> owner
    assert [q.to_tag for q in r.quarantine if q.reason == "unknown plus tag"] == ["mallory"]
