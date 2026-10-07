"""Repository-level guarantees: pinned contracts, no-bypass lint, CLI."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from mbos_governance.cli import main

REPO = Path(__file__).resolve().parents[1]
PINNED = {
    "action-request.schema.json": "38be3f152c69b343bddc54edc0d86d29cc9f0b8c09250e66cd5f9f49304055b3",
    "approval.schema.json": "d8593684adf1c622e7916f6e4aa068f73ff1bb38f62817f5606ce40e69072bc5",
    "provenance.schema.json": "15db68a4c6ef28d442209cd35e45970330653e7dff76ce5431bd8b05ec807b4c",
    "receipt.schema.json": "c6a55d47583541aef839bc66f5ecf07dcca187d0325b64b380a3a1bf52f155f9",
}


def test_contracts_match_frozen_v1():
    for name, digest in PINNED.items():
        data = (REPO / "src/mbos_governance/schemas" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, name


def _lint():
    spec = importlib.util.spec_from_file_location("check_no_bypass", REPO / "tools/check_no_bypass.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_bypass_in_repo():
    assert _lint().violations(REPO / "src") == []


def test_no_bypass_lint_catches_violation(tmp_path):
    (tmp_path / "agent.py").write_text("import smtplib\nfrom twilio.rest import Client\nx = __import__('requests')\n")
    assert len(_lint().violations(tmp_path)) == 3


def _role_env(monkeypatch, env):
    monkeypatch.delenv("MBOS_GOV_DSN", raising=False)
    for role, dsn in env.dsns.items():
        monkeypatch.setenv(f"MBOS_GOV_DSN_{role.upper()}", dsn)
    monkeypatch.setenv("MBOS_EGRESS_FILE", str(env.tmp / "egress.json"))
    monkeypatch.setenv("MBOS_LITELLM_FILE", str(env.tmp / "litellm.json"))


def test_cli_freeze_status_release(env, monkeypatch, capsys):
    _role_env(monkeypatch, env)
    base = ["--policy", str(env.policy_path)]
    assert main(base + ["panic", "status"]) == 0                       # env released the bootstrap freeze
    assert main(base + ["panic", "freeze", "--level", "L2", "--target", "money.*", "--actor", "michael",
                        "--reason", "x"]) == 0
    assert main(base + ["panic", "freeze", "--actor", "ops", "--reason", "stop"]) == 0
    assert main(base + ["panic", "status"]) == 2
    assert main(base + ["panic", "release", "--actor", "agent-07-marketing", "--reason", "x"]) == 1
    assert main(base + ["panic", "release", "--actor", "michael", "--reason", "go"]) == 0
    assert main(base + ["panic", "status"]) == 0
    assert main(base + ["ledger", "verify"]) == 0
    assert main(base + ["policy", "check"]) == 0
    out = capsys.readouterr().out
    assert "money.*" in out and json.loads((env.tmp / "egress.json").read_text())["default"] == "deny"


def test_cli_with_unreachable_database_reports_frozen(env, monkeypatch, capsys):
    bad = env.dsn("gateway").replace("dbname=", "dbname=gone_")
    monkeypatch.setenv("MBOS_GOV_DSN", bad)
    for role in ("GATEWAY", "APPROVER", "AGENT_WRITE", "POLICY_ADMIN"):
        monkeypatch.delenv(f"MBOS_GOV_DSN_{role}", raising=False)
    monkeypatch.chdir(env.tmp)
    base = ["--policy", str(env.policy_path)]
    assert main(base + ["panic", "status"]) == 2                       # unreadable => FROZEN
    assert main(base + ["panic", "freeze", "--actor", "michael", "--reason", "db gone"]) == 1
    assert "readable" in capsys.readouterr().out


def test_cli_applies_freeze_requests(env, monkeypatch, tmp_path):
    _role_env(monkeypatch, env)
    req = json.loads((REPO / "tests/data/b04/freeze-request-429.json").read_text())
    side = tmp_path / "side.jsonl"
    side.write_text(json.dumps({"kind": "freeze_request", "freeze_request": req}) + "\n")
    assert main(["--policy", str(env.policy_path), "freeze-requests", "apply", str(side)]) == 0
    assert env.panic.read().blocks("agent-02-opportunity", req["capability"], "discovery")


def test_vendored_lane_d_schema_is_pinned():
    """tests/vendor/agent04_state is a byte-identical, test-only copy of agent-04 @ 14bd690."""
    vendor = REPO / "tests/vendor/agent04_state"
    for line in (vendor / "MANIFEST.sha256").read_text().splitlines():
        digest, rel = line.split()
        assert hashlib.sha256((vendor / rel).read_bytes()).hexdigest() == digest, rel


def test_no_sqlite_on_the_production_path():
    for f in (REPO / "src").rglob("*.py"):
        assert "import sqlite3" not in f.read_text() and "sqlite3." not in f.read_text(), f
