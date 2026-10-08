"""D-09 part a: point-in-time recovery mechanics (WAL archive + base backup + restore) against a LOCAL directory.
The off-box destination later changes only the archive/target directory (docs/state/OWNER_QUESTION_BACKUPS.md)."""

import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import psycopg
import pytest

from mbos_state.provision import provision
from mbos_state.store import Actor, StateStore
from conftest import STATE_DIR, _pg_bin, key

BOOT = STATE_DIR / "bootstrap"
AGENT = Actor("agent", "agent-02-opportunity")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sh(cmd, env=None, check=True):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, check=check, env={**os.environ, **(env or {})})


class Src:
    """The live ('production') cluster, archiving WAL to a local directory."""


@pytest.fixture(scope="module")
def src(tmp_path_factory):
    pg = _pg_bin()
    root = tmp_path_factory.mktemp("pitr")
    short = Path(tempfile.mkdtemp(prefix="mbp-", dir="/tmp"))
    s = Src()
    s.pg, s.root, s.short = pg, root, short
    s.archive, s.target = root / "wal-archive", root / "backups"
    s.data, s.sock, s.port = root / "src-data", short / "s", free_port()
    s.sock.mkdir()
    sh([pg / "initdb", "-D", s.data, "--auth=trust", "-U", "postgres", "--encoding=UTF8", "--locale=C.UTF-8", "--data-checksums"])
    with (s.data / "postgresql.conf").open("a") as f:
        f.write(f"""
port = {s.port}
unix_socket_directories = '{s.sock}'
listen_addresses = ''
timezone = 'UTC'
wal_level = replica
archive_mode = on
archive_timeout = 300
archive_command = '{BOOT / "archive-wal.sh"} {s.archive} %p %f'
""")
    sh([pg / "pg_ctl", "-D", s.data, "-l", root / "src.log", "-w", "start"])
    s.dsn = f"host={s.sock} port={s.port} user=postgres dbname=postgres"
    p = provision(s.dsn, app_db="mbos", sys_db="mbos_sys")
    s.app = f"host={s.sock} port={s.port} user=postgres dbname=mbos"
    s.env = {"PG_BIN": str(pg), "MBOS_PGSOCK": str(s.sock), "MBOS_PGPORT": str(s.port),
             "MBOS_BACKUP_TARGET": str(s.target), "MBOS_BASEBACKUP_USER": "postgres"}
    conn = psycopg.connect(s.app, autocommit=True)
    store = StateStore(conn)
    pid = store.record_provenance(actor_type="system", basis="FACT", tool_name="pitr-test", tool_version="1")

    def seed(n, tag):
        for i in range(n):
            store.create_item({"type": "flip", "category": "trailer", "dedup_key": f"{tag}-{i}", "sources": [],
                               "normalized": {"title": f"{tag} {i}"}}, AGENT, f"seed {tag}", [pid], key("pitr"))

    def wait_archived():
        lsn = conn.execute("SELECT pg_switch_wal()").fetchone()[0]
        want = conn.execute("SELECT pg_walfile_name(%s::pg_lsn - 1)", (lsn,)).fetchone()[0]
        for _ in range(120):
            last, failed = conn.execute("SELECT last_archived_wal, failed_count FROM pg_stat_archiver").fetchone()
            if last and last >= want:
                return failed
            time.sleep(0.5)
        raise AssertionError(f"archiver never reached {want}")

    seed(5, "phase1")
    s.base = Path(sh([BOOT / "pitr-base-backup.sh"], s.env).stdout.strip())     # verified by pg_verifybackup inside
    seed(5, "phase2")
    conn.execute("SELECT pg_create_restore_point('good')")
    s.good_head = conn.execute("SELECT seq FROM mbos.chain_head()").fetchone()[0]
    seed(5, "phase3-after-good")
    s.final_head = conn.execute("SELECT seq FROM mbos.chain_head()").fetchone()[0]
    s.archiver_failed = wait_archived()
    conn.close()
    sh([pg / "pg_ctl", "-D", s.data, "-m", "fast", "-w", "stop"])
    yield s
    sh([pg / "pg_ctl", "-D", s.data, "-m", "immediate", "-w", "stop"], check=False)
    shutil.rmtree(short, ignore_errors=True)


def restore(src, name, archive=None, **mode):
    data, sock, port = src.root / f"restore-{name}", src.short / f"r-{name}", free_port()
    args = [BOOT / "restore-pitr.sh", "--base", src.base, "--archive", archive or src.archive, "--data", data,
            "--port", port, "--sock", sock]
    for k, v in mode.items():
        args += [f"--{k.replace('_', '-')}"] + ([] if v is True else [v])
    cp = sh(args, {"PG_BIN": str(src.pg), "MBOS_RESTORE_TIMEOUT": "30", "MBOS_BASEBACKUP_USER": "postgres"}, check=False)
    return cp, data, f"host={sock} port={port} user=postgres dbname=mbos"


def stop(src, data):
    sh([src.pg / "pg_ctl", "-D", data, "-m", "immediate", "-w", "stop"], check=False)


def test_archive_and_base_backup_are_healthy(src):
    assert src.archiver_failed == 0
    assert (src.base / "backup_manifest").exists()
    archived = sorted(p.name for p in src.archive.iterdir() if not p.name.startswith(".tmp."))
    assert archived and all(len(n) == 24 or n.endswith(".history") or ".backup" in n for n in archived), archived
    assert not [p for p in src.archive.iterdir() if p.name.startswith(".tmp.")]       # no half-written files
    assert all(not (src.archive / n).stat().st_mode & 0o222 for n in archived)         # archived files are read-only


def test_restore_to_named_point_returns_exactly_that_state(src):
    cp, data, dsn = restore(src, "good", target_name="good")
    try:
        assert cp.returncode == 0, cp.stderr
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT count(*) FROM mbos.items").fetchone()[0] == 10          # phase 1 + 2, not phase 3
            assert c.execute("SELECT seq FROM mbos.chain_head()").fetchone()[0] == src.good_head
            assert c.execute("SELECT count(*) FROM mbos.items WHERE dedup_key LIKE 'phase3%'").fetchone()[0] == 0
            ok = c.execute("SELECT ok, receipts_checked FROM mbos.verify_chain()").fetchone()
            assert ok == (True, src.good_head)
            # promoted: it accepts writes and the chain continues gapless
            store = StateStore(c)
            pid = store.record_provenance(actor_type="system", basis="FACT", tool_name="t", tool_version="1")
            store.create_item({"type": "flip", "category": "tool", "dedup_key": "after-restore", "sources": [],
                               "normalized": {}}, AGENT, "post-restore write", [pid], key())
            assert store.verify_chain().ok and store.chain_head()["seq"] > src.good_head
    finally:
        stop(src, data)


def test_restore_latest_replays_everything_archived(src):
    cp, data, dsn = restore(src, "latest", latest=True)
    try:
        assert cp.returncode == 0, cp.stderr
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT count(*) FROM mbos.items").fetchone()[0] == 15
            assert c.execute("SELECT seq FROM mbos.chain_head()").fetchone()[0] == src.final_head
            assert c.execute("SELECT ok FROM mbos.verify_chain()").fetchone()[0]
    finally:
        stop(src, data)


def test_restore_with_missing_wal_fails_instead_of_promoting_short(src, tmp_path):
    empty = tmp_path / "empty-archive"
    empty.mkdir()
    cp, data, dsn = restore(src, "missing", archive=empty, target_name="good")
    try:
        assert cp.returncode != 0 and "restore FAILED" in cp.stderr
        with pytest.raises(psycopg.OperationalError):                      # nothing is serving a shorter history
            psycopg.connect(dsn, connect_timeout=2)
    finally:
        stop(src, data)


def test_restore_refuses_to_overwrite_an_existing_directory(src):
    data = src.root / "exists"
    data.mkdir()
    cp = sh([BOOT / "restore-pitr.sh", "--base", src.base, "--archive", src.archive, "--data", data, "--port", "1",
             "--sock", src.short / "x", "--latest"], {"PG_BIN": str(src.pg)}, check=False)
    assert cp.returncode == 2 and "already exists" in cp.stderr


def test_restored_cluster_cannot_write_into_the_archive(src):
    before = sorted(p.name for p in src.archive.iterdir())
    cp, data, dsn = restore(src, "noarch", latest=True)
    try:
        assert cp.returncode == 0, cp.stderr
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SHOW archive_mode").fetchone()[0] == "off"
            c.execute("SELECT pg_switch_wal()")
    finally:
        stop(src, data)
    assert sorted(p.name for p in src.archive.iterdir()) == before


def test_archive_command_is_idempotent_and_refuses_to_overwrite(tmp_path):
    dest, f = tmp_path / "arch", tmp_path / "seg"
    f.write_bytes(b"A" * 1024)
    run = lambda p: subprocess.run([str(BOOT / "archive-wal.sh"), str(dest), str(p), "000000010000000000000001"],
                                   capture_output=True, text=True)
    assert run(f).returncode == 0
    assert run(f).returncode == 0                                          # a retry after a crash is fine
    other = tmp_path / "seg2"
    other.write_bytes(b"B" * 1024)
    r = run(other)
    assert r.returncode == 1 and "refusing to overwrite" in r.stderr       # a different file with the same name
    assert (dest / "000000010000000000000001").read_bytes() == b"A" * 1024
    assert not [p for p in dest.iterdir() if p.name.startswith(".tmp.")]
