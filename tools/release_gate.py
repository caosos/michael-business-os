"""Wave-two release gate (A-02). One command; exits non-zero on any failure; writes docs/status/RELEASE_GATE.md.

    .venv/bin/python -I tools/release_gate.py [--fetch]

Checks: frozen contracts · ADR-0010 vectors · full test suite · cross-lane interop (every lane's pushed code) ·
lane-D/E end-to-end with lane C's real engine + 05's real gateway · lane C's strict AT-1 replay audit of that run.
Everything is DRY-RUN; the lane-D/E run uses a throwaway local PostgreSQL 16.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv" / "bin" / "python")
LANES = ["01-coordinator", "02-opportunity", "03-economics", "04-state", "05-governance", "06-communications", "07-marketing"]


def run(name: str, cmd: list[str], timeout: int = 1800, env: dict | None = None) -> dict:
    t = time.monotonic()
    cp = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env={**os.environ, **(env or {})})
    tail = (cp.stdout + cp.stderr).strip().splitlines()
    return {"name": name, "ok": cp.returncode == 0, "rc": cp.returncode, "secs": round(time.monotonic() - t, 1),
            "summary": tail[-1] if tail else "", "stdout": cp.stdout}


def at1_lane_de() -> dict:
    """Fresh lane-D DB (04's head) + 05's whole policy dir; lane C engine; strict AT-1 audit of the export."""
    sys.path.insert(0, str(ROOT))
    import pgserver

    from tests.helpers import lane_d
    from tests.helpers.common import fixture_variant

    tmp = Path(tempfile.mkdtemp(prefix="mbos-gate-"))
    src = tmp / "src"
    src.mkdir()
    lane_d.extract(src)
    tar = subprocess.run(["git", "archive", "origin/research/agent-05-governance", "policy"], cwd=ROOT,
                         capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(tmp, filter="data")
    server = pgserver.get_server(str(tmp / "pg"), cleanup_mode="stop")
    try:
        app = lane_d.build(server, src, "mbos_gate")
        server.psql("CREATE DATABASE mbos_gate_sys;")
        fx = fixture_variant(tmp, "gate", ["FIX-TRAILER-1", "FIX-LEAD-SMARTHOME-1", "FIX-MOWER-1", "FIX-LEAD-DRYWALL-1"])
        r = run("lane D/E e2e + AT-1", [PY, "-m", "tests.helpers.runner", "lane_d_e2e", str(fx), "lane_e"], timeout=300,
                env={"MBOS_DATABASE_URL": app, "MBOS_SYSTEM_DATABASE_URL": server.get_uri().replace("/postgres?", "/mbos_gate_sys?"),
                     "MBOS_POLICY_PATH": str(tmp / "policy" / "policy.v1.json"), "MBOS_SCORER": "engine"})
    finally:
        server.cleanup()
    res = next((json.loads(line[len("RESULT"):]) for line in r["stdout"].splitlines() if line.startswith("RESULT")), None)
    ok = bool(r["ok"] and res and res["chain"]["ok"] and res["reference_chain"][0] and res["live_effector_calls"] == 0
              and not res["contract_errors"] and res["at1"] and res["at1"]["ok"] and res["at1"]["drift_count"] == 0)
    summary = "no RESULT" if not res else (
        f"chain {res['chain']['checked']} ok={res['chain']['ok']} · reference {res['reference_chain'][1]} · "
        f"effector {res['effector_calls']} (live {res['live_effector_calls']}) · contract errors {len(res['contract_errors'])} · "
        f"AT-1 {res['at1']} · final {res['final']}")
    return {"name": "lane D/E e2e + strict AT-1 (03 engine, 05 gateway, 04 schema)", "ok": ok, "rc": r["rc"],
            "secs": r["secs"], "summary": summary}


def main() -> int:
    if "--fetch" in sys.argv:
        subprocess.run(["git", "fetch", "-q", "origin"], cwd=ROOT)
    heads = {l: subprocess.run(["git", "rev-parse", "--short", f"origin/research/agent-{l}"], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip() for l in LANES}
    heads["01-coordinator (local HEAD)"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                                          capture_output=True, text=True).stdout.strip()
    checks = [
        run("frozen contracts (validate_contracts.py)", [PY, "-I", "docs/research/contracts/validate_contracts.py", "docs/research/contracts"]),
        run("ADR-0010 vectors (reference self-test)", [PY, "-I", "docs/research/contracts/canonical/mbos_canonical.py",
                                                      "docs/research/contracts/canonical/vectors.json"]),
        run("full test suite (pytest)", [PY, "-m", "pytest", "-q"]),
        run("cross-lane interop (tools/interop_check.py)", [PY, "-I", "tools/interop_check.py"]),
        at1_lane_de(),
    ]
    ic = checks[3]
    ic["summary"] = f"{ic['stdout'].count('CONFORMS')}/6 Python lanes CONFORM (vectors + rejections + vendored-copy identity)"
    ok = all(c["ok"] for c in checks)
    lines = [f"# Release gate: wave two ({'PASS' if ok else 'FAIL'})", "",
             f"- **Run:** {time.strftime('%Y-%m-%d %H:%M %z')}", "- **Command:** `.venv/bin/python -I tools/release_gate.py --fetch`",
             "- **Mode:** DRY-RUN only. Throwaway local PostgreSQL 16.", "", "## Lane heads tested", "",
             "| Lane | Commit |", "|---|---|"] + [f"| {k} | `{v}` |" for k, v in heads.items()] + [
             "", "## Checks", "", "| Check | Result | Time | Summary |", "|---|---|---|---|"] + [
             f"| {c['name']} | {'PASS' if c['ok'] else 'FAIL (rc ' + str(c['rc']) + ')'} | {c['secs']}s | {c['summary'].replace('|', '/')[:600]} |"
             for c in checks] + [
             "", "## Coverage notes", "",
             "- **Action path with 05's real gateway on lane D:** `tests/integration/test_spine_on_lane_d.py::test_full_lifecycle_with_lane_e_gateway`"
             " (inside the full suite). YES→ACTED, exactly one ACTION_EXECUTING by the gateway, 1 dry-run effector call, 0 live.",
             "- **Real-engine scoring + strict AT-1:** the lane D/E run with lane C's engine. Fixture items the engine scores"
             " MAYBE/PASS park or archive, so this run may execute no action. That is by design: the action path is covered above.",
             "- **Lane G (07):** the independent `qa/` A1–A10 + G1–G4 re-run on lanes D/E is task G-04, reported on 07's branch."]
    out = ROOT / "docs" / "status" / "RELEASE_GATE.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
