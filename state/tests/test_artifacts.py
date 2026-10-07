"""D-07: filesystem artifact store — round trip, idempotency, tamper detection, index rules, drill hooks."""

import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg import errors

from mbos_state.artifacts import ArtifactError, ArtifactStore, ArtifactTampered, rel_path, sha256_hex

STATE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def store(db, tmp_path):
    return ArtifactStore(db.connect("agent_write"), tmp_path / "artifacts")


def test_round_trip_layout_and_index(store, db):
    data = b"\x89PNG fake photo of a 6x12 trailer"
    sha = store.put(data, "image/png")
    assert sha == sha256_hex(data)
    f = store.root / rel_path(sha)
    assert f.read_bytes() == data and not (f.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    assert store.get(sha) == data
    row = db.connect().execute("SELECT storage, location, byte_size, content FROM mbos.artifacts WHERE sha256=%s",
                               (sha,)).fetchone()
    assert row == ("fs", rel_path(sha), len(data), None)
    assert store.put(data, "image/png") == sha                         # idempotent
    assert db.connect().execute("SELECT count(*) FROM mbos.artifacts").fetchone()[0] == 1
    assert store.verify_all() == []


def test_inline_artifacts_read_through_same_api(store, db):
    sha = db.connect("agent_write").execute("SELECT mbos.put_artifact(%s, 'text/plain')", (b"inline",)).fetchone()[0]
    assert store.get(sha) == b"inline"


@pytest.mark.parametrize("damage", ["modify", "truncate", "delete"])
def test_tamper_detected(store, damage):
    sha = store.put(b"quote PDF bytes " * 100, "application/pdf")
    f = store.root / rel_path(sha)
    os.chmod(f, 0o644)
    if damage == "modify":
        b = bytearray(f.read_bytes()); b[10] ^= 0x01; f.write_bytes(bytes(b))
    elif damage == "truncate":
        f.write_bytes(f.read_bytes()[:-1])
    else:
        f.unlink()
    with pytest.raises(ArtifactTampered):
        store.get(sha)
    assert len(store.verify_all()) == 1


def test_put_never_overwrites_a_tampered_file(store):
    data = b"receipt scan"
    sha = store.put(data, "image/jpeg")
    f = store.root / rel_path(sha)
    os.chmod(f, 0o644)
    f.write_bytes(b"evil")
    with pytest.raises(ArtifactTampered):
        store.put(data, "image/jpeg")
    assert f.read_bytes() == b"evil"          # evidence kept for inspection, not silently repaired


def test_unindexed_files_are_reported(store):
    store.put(b"a", "text/plain")
    stray = store.root / rel_path(sha256_hex(b"stray"))
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"stray")
    assert any("unindexed" in p for p in store.verify_all())


def test_index_rules(db):
    w = db.connect("agent_write")
    h = "sha256:" + hashlib.sha256(b"x").hexdigest()
    with pytest.raises(errors.CheckViolation):                   # index cannot point at an arbitrary path
        w.execute("INSERT INTO mbos.artifacts (sha256, media_type, byte_size, storage, location) "
                  "VALUES (%s, 'x', 1, 'fs', '../../etc/passwd')", (h,))
    w.execute("SELECT mbos.register_artifact(%s, 'text/plain', 1)", (h,))
    with pytest.raises(errors.InsufficientPrivilege):
        db.connect("reader").execute("SELECT mbos.register_artifact(%s, 'text/plain', 1)", (h,))
    with pytest.raises(errors.InsufficientPrivilege):
        w.execute("DELETE FROM mbos.artifacts")
    with pytest.raises(psycopg.Error) as ei:
        db.connect("owner").execute("UPDATE mbos.artifacts SET location = 'x'")
    assert ei.value.sqlstate == "MB001"
    with pytest.raises(ArtifactError):
        rel_path("sha256:../../etc")


def test_cli_verify_artifacts_against_a_backup_copy(store, db, tmp_path):
    import shutil
    sha = store.put(b"listing photo", "image/jpeg")
    backup = tmp_path / "backup-artifacts"
    shutil.copytree(store.root, backup)
    env = {**os.environ, "PYTHONPATH": str(STATE_DIR), "MBOS_DSN": db.dsn("reader")}
    ok = subprocess.run([sys.executable, "-m", "mbos_state", "verify-artifacts", "--root", str(backup)],
                        env=env, capture_output=True, text=True)
    assert ok.returncode == 0 and "OK: 1 artifacts checked" in ok.stdout
    f = backup / rel_path(sha)
    os.chmod(f, 0o644)
    f.write_bytes(b"swapped")
    bad = subprocess.run([sys.executable, "-m", "mbos_state", "verify-artifacts", "--root", str(backup)],
                         env=env, capture_output=True, text=True)
    assert bad.returncode == 1 and "modified" in bad.stdout
