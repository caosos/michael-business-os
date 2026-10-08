"""Wave-two release gate (A-02). One command; exits non-zero on any failure; writes docs/status/RELEASE_GATE.md.

    .venv/bin/python -I tools/release_gate.py [--no-fetch]   # fetches origin by default so it checks the REAL pushed heads

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
            "summary": tail[-1] if tail else "", "stdout": cp.stdout, "stderr": cp.stderr}


def contracts_pinned() -> dict:
    """F-46: the frozen contract bytes must match their pin (changing one needs an accepted ADR + semver bump)."""
    r = run("frozen contracts pinned (FROZEN.sha256.json)", [PY, "-I", "tools/pin_contracts.py"])
    r["summary"] = " ".join(r["stdout"].strip().splitlines()[:6])[:300]
    return r


def suite_floor(pytest_result: dict) -> dict:
    """F-47: the suite must pass AND run enough tests: an all-skipped or shrunken suite is a red gate."""
    import re

    floor = json.loads((ROOT / "tools" / "release_gate_floor.json").read_text())
    out = pytest_result["stdout"]
    n = lambda w: int((re.search(rf"(\d+) {w}", out) or [0, 0])[1])
    passed, skipped, failed = n("passed"), n("skipped"), n("failed") + n("error")
    ok = pytest_result["ok"] and passed >= floor["min_passed"] and skipped <= floor["max_skipped"] and failed <= floor["max_failed"]
    return {"name": "suite floor (tools/release_gate_floor.json)", "ok": ok, "rc": 0 if ok else 1, "secs": 0.0,
            "summary": f"passed {passed} (min {floor['min_passed']}), skipped {skipped} (max {floor['max_skipped']}), failed {failed}"}


def pins_check() -> dict:
    """07's lesson: after a re-pin pip can silently keep OLD code (same version string, stale build/ dir). Compare every
    installed lane package, byte for byte, with the pushed head the gate reports."""
    import importlib.util

    pairs = [("mbos_economics", "research/agent-03-economics", "economics/src/mbos_economics"),
             ("mbos_governance", "research/agent-05-governance", "src/mbos_governance")]
    bad, notes = [], []
    for pkg, branch, path in pairs:
        spec = importlib.util.find_spec(pkg)
        if spec is None or not spec.submodule_search_locations:
            bad.append(f"{pkg}: not installed")
            continue
        root = Path(list(spec.submodule_search_locations)[0])
        tar = subprocess.run(["git", "archive", f"origin/{branch}", path], cwd=ROOT, capture_output=True)
        if tar.returncode:
            bad.append(f"{pkg}: cannot read {branch}")
            continue
        with tarfile.open(fileobj=io.BytesIO(tar.stdout)) as t:
            files = {Path(m.name).relative_to(path).as_posix(): t.extractfile(m).read()
                     for m in t.getmembers() if m.isfile() and "__pycache__" not in m.name and not m.name.endswith(".pyc")}
        installed = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                     and p.suffix != ".pyc"}  # F-50: ANY file type counts (.txt .sql .so .pth ...)
        diff = [f for f, data in files.items() if (root / f).exists() and (root / f).read_bytes() != data]  # .py AND .json (F-48)
        missing = [f for f in files if not (root / f).exists()]
        extra = sorted(installed - set(files))  # a stale extra file is drift too (F-48)
        notes.append(f"{pkg} {len(files)} files vs {branch}")
        if diff or missing or extra:
            bad.append(f"{pkg}: {len(diff)} differ ({', '.join(diff[:3])}), {len(missing)} missing, {len(extra)} extra ({', '.join(extra[:3])})")
    return {"name": "installed lane packages == pushed heads (no stale installs)", "ok": not bad, "rc": 0 if not bad else 1,
            "secs": 0.0, "summary": "; ".join(bad) if bad else "identical: " + "; ".join(notes)}


def _runs_as_worker(res: dict | None) -> bool:
    """A-01 phase 2: the e2e must run as the real non-superuser worker login, or it proves less than production does."""
    roles = (res or {}).get("roles") or {}
    return bool(res and res.get("db_login") and res["db_login"][0] == "mbos_dbos" and res["db_login"][1] is False
                and roles.get("worker") == [False, False] and roles.get("owner") == [True, True])   # D-26: worker holds neither approver nor owner_channel


def action_path_verdict(run_ok: bool, res: dict | None) -> bool:
    """F-49/F-50: the action-path check must be NON-EMPTY: real executions, zero live effector calls, a verifying chain,
    one live pending follow-up, and a PANIC drill that blocks while frozen and not after release."""
    try:
        return bool(run_ok and res and res["chain"]["ok"] and res["reference_chain"][0] and res["live_effector_calls"] == 0
                    and res["effector_calls"] >= 2 and res["executed"] >= 2 and not res["contract_errors"]
                    and res["followup"] and res["followup"]["concurrent"]["live_pending"] == 1
                    and res["panic"] and res["panic"]["frozen_blocks"] and not res["panic"]["released_blocks"])
    except (KeyError, TypeError, IndexError):
        return False


def action_path_lane_de() -> dict:
    """F-49: the strict-AT-1 run uses lane C's real engine, which rarely says YES on fixtures, so it executes no action.
    This run uses the stand-in scorer so the ACTION path (approval -> real gateway -> dry-run effector -> follow-up ->
    PANIC drill) really executes, and asserts the live-effector check is NOT empty."""
    sys.path.insert(0, str(ROOT))
    import pgserver

    from tests.helpers import lane_d
    from tests.helpers.common import fixture_variant

    tmp = Path(tempfile.mkdtemp(prefix="mbos-gate-act-"))
    src = tmp / "src"
    src.mkdir()
    lane_d.extract(src)
    tar = subprocess.run(["git", "archive", "origin/research/agent-05-governance", "policy"], cwd=ROOT, capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(tmp, filter="data")
    server = pgserver.get_server(str(tmp / "pg"), cleanup_mode="stop")
    try:
        app, sysu, ownu = lane_d.build_as_worker(server, src, "mbos_gate_act")   # the real mbos_dbos login, no superuser (A-01 phase 2)
        fx = fixture_variant(tmp, "gate", ["FIX-TRAILER-1", "FIX-LEAD-SMARTHOME-1", "FIX-MOWER-1"])
        r = run("action path", [PY, "-m", "tests.helpers.runner", "lane_d_e2e", str(fx), "lane_e"], timeout=300,
                env={"MBOS_DATABASE_URL": app, "MBOS_SYSTEM_DATABASE_URL": sysu, "MBOS_OWNER_DATABASE_URL": ownu,
                     "MBOS_POLICY_PATH": str(tmp / "policy" / "policy.v1.json"),
                     "MBOS_EGRESS_FILE": str(tmp / "egress.json"), "MBOS_LITELLM_FILE": str(tmp / "litellm.json")})
    finally:
        server.cleanup()
    res = next((json.loads(line[len("RESULT"):]) for line in r["stdout"].splitlines() if line.startswith("RESULT")), None)
    ok = action_path_verdict(bool(r["ok"]), res) and _runs_as_worker(res)
    summary = "no RESULT" if not res else (f"login {res.get('db_login')} · effector calls {res['effector_calls']} (live {res['live_effector_calls']}) · executed {res['executed']} · "
                                           f"follow-up {res['followup']} · panic drill {res['panic'] and res['panic']['frozen_blocks']} · chain ok {res['chain']['ok']}")
    return {"name": "lane D/E ACTION path (real gateway, follow-up, PANIC drill, live effector rows must be 0 and >=2 calls)",
            "ok": ok, "rc": r["rc"], "secs": r["secs"], "summary": summary[:600]}


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
        app, sysu, ownu = lane_d.build_as_worker(server, src, "mbos_gate")   # the real mbos_dbos login, no superuser (A-01 phase 2)
        fx = fixture_variant(tmp, "gate", ["FIX-TRAILER-1", "FIX-LEAD-SMARTHOME-1", "FIX-MOWER-1", "FIX-LEAD-DRYWALL-1"])
        r = run("lane D/E e2e + AT-1", [PY, "-m", "tests.helpers.runner", "lane_d_e2e", str(fx), "lane_e"], timeout=300,
                env={"MBOS_DATABASE_URL": app, "MBOS_SYSTEM_DATABASE_URL": sysu, "MBOS_OWNER_DATABASE_URL": ownu,
                     "MBOS_POLICY_PATH": str(tmp / "policy" / "policy.v1.json"), "MBOS_SCORER": "engine",
                     "MBOS_EGRESS_FILE": str(tmp / "egress.json"), "MBOS_LITELLM_FILE": str(tmp / "litellm.json")})
    finally:
        server.cleanup()
    res = next((json.loads(line[len("RESULT"):]) for line in r["stdout"].splitlines() if line.startswith("RESULT")), None)
    ok = bool(r["ok"] and res and _runs_as_worker(res) and res["chain"]["ok"] and res["reference_chain"][0] and res["live_effector_calls"] == 0
              and not res["contract_errors"] and res["at1"] and res["at1"]["ok"] and res["at1"]["drift_count"] == 0)
    summary = ("no RESULT: " + " ".join((r["stdout"] + r.get("stderr", "")).strip().splitlines()[-2:])[:300]) if not res else (
        f"chain {res['chain']['checked']} ok={res['chain']['ok']} · reference {res['reference_chain'][1]} · "
        f"login {res['db_login'][0]} (superuser={res['db_login'][1]}) · effector {res['effector_calls']} (live {res['live_effector_calls']}) · contract errors {len(res['contract_errors'])} · "
        f"AT-1 {res['at1']} · final {res['final']}")
    return {"name": "lane D/E e2e + strict AT-1 (03 engine, 05 gateway, 04 schema)", "ok": ok, "rc": r["rc"],
            "secs": r["secs"], "summary": summary}


def main() -> int:
    fetch_check = None
    if "--no-fetch" not in sys.argv:  # F-48: compare against the REAL pushed heads, not stale local refs
        fr = subprocess.run(["git", "fetch", "-q", "origin"], cwd=ROOT, capture_output=True, text=True)  # F-50: a failed fetch is RED
        fetch_check = {"name": "git fetch origin (the gate must compare against REAL pushed heads)", "ok": fr.returncode == 0, "rc": fr.returncode,
                       "secs": 0.0, "summary": "ok" if fr.returncode == 0 else f"FAILED rc={fr.returncode}: {fr.stderr.strip()[:200]}"}
    heads = {l: subprocess.run(["git", "rev-parse", "--short", f"origin/research/agent-{l}"], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip() for l in LANES}
    heads["01-coordinator (local HEAD)"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                                          capture_output=True, text=True).stdout.strip()
    pytest_check = run("full test suite (pytest)", [PY, "-m", "pytest", "-q"])
    checks = ([fetch_check] if fetch_check else []) + [
        run("frozen contracts (validate_contracts.py)", [PY, "-I", "docs/research/contracts/validate_contracts.py", "docs/research/contracts"]),
        contracts_pinned(),
        run("ADR-0010 vectors (reference self-test)", [PY, "-I", "docs/research/contracts/canonical/mbos_canonical.py",
                                                      "docs/research/contracts/canonical/vectors.json"]),
        pytest_check,
        suite_floor(pytest_check),
        run("cross-lane interop (tools/interop_check.py)", [PY, "-I", "tools/interop_check.py"]),
        pins_check(),
        action_path_lane_de(),
        at1_lane_de(),
    ]
    ic = next(c for c in checks if c["name"].startswith("cross-lane interop"))
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
