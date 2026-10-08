"""A-38: tools/bootstrap_dev.py gives a real lane D environment with split logins and separate env files."""

from __future__ import annotations

import importlib.util
import os
import stat

import psycopg
import pytest

from tests.helpers.common import ROOT


def _load():
    spec = importlib.util.spec_from_file_location("bootstrap_dev", ROOT / "tools" / "bootstrap_dev.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _env(path):
    out = {}
    for line in path.read_text().splitlines():
        if line.startswith("export "):
            k, v = line[7:].split("=", 1)
            out[k] = v.strip("'")
    return out


def test_bootstrap_writes_worker_and_owner_env(tmp_path, monkeypatch, capsys):
    pytest.importorskip("pgserver")
    monkeypatch.setenv("MBOS_DEVDB_DIR", str(tmp_path / "pg"))
    try:
        assert _load().main(["--skip-install", "--var-dir", str(tmp_path / "var")]) == 0
        dev, owner = _env(tmp_path / "var" / "dev.env"), _env(tmp_path / "var" / "owner.env")
        assert dev["MBOS_STATE_BACKEND"] == "lane_d" and dev["MBOS_GATEWAY_MODE"] == "lane_e"
        assert set(dev) >= {"MBOS_DATABASE_URL", "MBOS_SYSTEM_DATABASE_URL", "MBOS_RAW_DIR", "MBOS_POLICY_PATH", "PYTHONPATH"}
        assert "MBOS_OWNER_DATABASE_URL" not in dev and set(owner) == {"MBOS_OWNER_DATABASE_URL"}
        assert stat.S_IMODE((tmp_path / "var" / "owner.env").stat().st_mode) == 0o600
        assert os.path.exists(dev["MBOS_POLICY_PATH"])
        with psycopg.connect(dev["MBOS_DATABASE_URL"]) as c:
            assert c.execute("select current_user, pg_has_role(current_user,'approver','member')").fetchone() == ("mbos_dbos", False)
        with psycopg.connect(owner["MBOS_OWNER_DATABASE_URL"]) as c:
            assert c.execute("select current_user, pg_has_role(current_user,'approver','member')").fetchone() == ("mbos_operator_ui", True)
            assert c.execute("select count(*) from mbos.panic_current").fetchone() == (0,)  # F-89: born FROZEN, released: system RUNNING
        out = capsys.readouterr().out
        assert "released the initial global freeze" in out and "MBOS_OWNER_DATABASE_URL" in out
    finally:
        import pgserver

        pgserver.get_server(tmp_path / "pg", cleanup_mode="stop").cleanup()


def test_keep_frozen_leaves_the_initial_freeze_and_says_so(tmp_path, monkeypatch, capsys):
    pytest.importorskip("pgserver")
    monkeypatch.setenv("MBOS_DEVDB_DIR", str(tmp_path / "pg"))
    try:
        assert _load().main(["--skip-install", "--keep-frozen", "--var-dir", str(tmp_path / "var")]) == 0
        with psycopg.connect(_env(tmp_path / "var" / "owner.env")["MBOS_OWNER_DATABASE_URL"]) as c:
            assert c.execute("select count(*) from mbos.panic_current where level = 'L3'").fetchone() == (1,)
        assert "left FROZEN" in capsys.readouterr().out
    finally:
        import pgserver

        pgserver.get_server(tmp_path / "pg", cleanup_mode="stop").cleanup()
