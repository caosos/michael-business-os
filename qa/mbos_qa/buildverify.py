"""Independent build verification: run each lane's OWN test suite from a clean `git archive` of its branch
head, in a fresh venv, and compare with the count the lane claims.

Read-only with respect to every other lane: nothing is checked out in a peer worktree, nothing is pushed
anywhere but this branch. Package installs come from PyPI. No test is edited or skipped.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

REPO = pathlib.Path(__file__).resolve().parent.parent.parent

# Env a lane documents as required when installed non-editable (its own error message names the variable).
LANE_ENV = {"01": {"MBOS_CONTRACTS_DIR": "{proj}/docs/research/contracts"}}

# lane: (branch, project subdir, pip install spec relative to subdir, extra pip packages, claimed count, claim source)
LANES = {
    "01": ("research/agent-01-coordinator", ".", ".[dev]", [], 111, "01 AGENT_STATUS (01 ran it)"),
    "02": ("research/agent-02-opportunity", ".", ".[dev]", [], 56, "ROUND_TWO_INTEGRATION table"),
    "03": ("research/agent-03-economics", "economics", ".[test]", [], 75, "ROUND_TWO_INTEGRATION table"),
    "04": ("research/agent-04-state", "state", ".[test]", [], 93, "ROUND_TWO_INTEGRATION table"),
    "05": ("research/agent-05-governance", ".", ".[test]", [], 114, "ROUND_TWO_INTEGRATION table"),
    "06": ("research/agent-06-communications", ".", None, ["pytest>=8", "jsonschema>=4.18"], 29,
           "ROUND_TWO_INTEGRATION table"),
}


def _run(cmd, cwd, log, env=None, timeout=1800):
    with open(log, "a") as fh:
        fh.write(f"\n$ {' '.join(map(str, cmd))}\n")
        fh.flush()
        return subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, env=env, timeout=timeout).returncode


def verify_lane(lane: str, base: pathlib.Path, python: str) -> dict:
    branch, sub, spec, extra, claimed, claim_src = LANES[lane]
    commit = subprocess.run(["git", "rev-parse", f"origin/{branch}"], cwd=REPO, capture_output=True,
                            text=True, check=True).stdout.strip()
    root = base / f"lane{lane}"
    shutil.rmtree(root, ignore_errors=True)
    src = root / "src"
    src.mkdir(parents=True)
    log = root / "build.log"
    t0 = time.time()
    archive = subprocess.run(["git", "archive", commit], cwd=REPO, capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(src)], input=archive, check=True)
    proj = src / sub
    venv = root / "venv"
    out = {"lane": lane, "branch": branch, "commit": commit[:7], "claimed": claimed, "claim_source": claim_src}
    if _run([python, "-m", "venv", str(venv)], root, log):
        return {**out, "status": "SETUP_FAILED", "detail": "venv"}
    pip = [str(venv / "bin" / "python"), "-m", "pip", "install", "-q", "--disable-pip-version-check"]
    if spec and _run(pip + [spec], proj, log):
        return {**out, "status": "SETUP_FAILED", "detail": f"pip install {spec} (see build.log)"}
    if extra and _run(pip + extra, proj, log):
        return {**out, "status": "SETUP_FAILED", "detail": f"pip install {extra}"}
    junit = root / "junit.xml"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "MBOS_QA_IMPL", "VIRTUAL_ENV")}
    env["PATH"] = f"{venv / 'bin'}:{env['PATH']}"
    for k, v in LANE_ENV.get(lane, {}).items():
        env[k] = v.format(proj=proj)
        out.setdefault("env", {})[k] = v
    rc = _run([str(venv / "bin" / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider",
               f"--junitxml={junit}"], proj, log, env=env)
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    failed = []
    if junit.exists():
        for ts in ET.parse(junit).getroot().iter("testsuite"):
            for k in counts:
                counts[k] += int(ts.get(k, 0))
        for tc in ET.parse(junit).getroot().iter("testcase"):
            if any(c.tag in ("failure", "error") for c in tc):
                failed.append(f"{tc.get('classname')}::{tc.get('name')}")
    passed = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    status = "PASS" if rc == 0 and not failed else "FAIL"
    match = "matches claim" if counts["tests"] == claimed else f"collected {counts['tests']} ≠ claimed {claimed}"
    return {**out, "status": status, "pytest_rc": rc, **counts, "passed": passed, "claim_check": match,
            "failed_tests": failed[:20], "seconds": round(time.time() - t0), "log": str(log)}


def run(base: pathlib.Path, lanes=None, python: str | None = None) -> list[dict]:
    python = python or shutil.which("python3.12") or sys.executable
    base.mkdir(parents=True, exist_ok=True)
    lanes = lanes or list(LANES)
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        res = list(ex.map(lambda ln: _safe(ln, base, python), lanes))
    return sorted(res, key=lambda r: r["lane"])


def _safe(lane, base, python):
    try:
        return verify_lane(lane, base, python)
    except Exception as e:  # noqa: BLE001 — report, never hide
        return {"lane": lane, "status": "SETUP_FAILED", "detail": f"{type(e).__name__}: {e}",
                "claimed": LANES[lane][4], "branch": LANES[lane][0], "commit": "?"}


def render(results: list[dict], python_version: str) -> str:
    L = ["# Independent build verification (lane G)", "",
         "> Generated by `python -m mbos_qa builds`. Each lane's **own** test suite was run from a clean "
         "`git archive` of its branch head, in a fresh venv, without touching any peer worktree. No test was "
         f"edited or deselected. Interpreter: {python_version}.", "",
         "| Lane | Head | Result | Collected | Passed | Failed | Errors | Skipped | Claimed | Claim check | Time |",
         "|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|"]
    for r in results:
        if r["status"] == "SETUP_FAILED":
            L.append(f"| {r['lane']} | `{r.get('commit')}` | **SETUP_FAILED** | — | — | — | — | — | {r['claimed']} | "
                     f"{r.get('detail', '')} | — |")
            continue
        L.append(f"| {r['lane']} | `{r['commit']}` | **{r['status']}** | {r['tests']} | {r['passed']} | {r['failures']} | "
                 f"{r['errors']} | {r['skipped']} | {r['claimed']} | {r['claim_check']} | {r['seconds']}s |")
    notes = [f"- Lane {r['lane']} ran with the env its own error message documents ({r['env']}): a non-editable "
             "install cannot find the contracts by relative path (finding F-16)." for r in results if r.get("env")]
    if notes:
        L += [""] + notes
    fails = [r for r in results if r.get("failed_tests")]
    if fails:
        L += ["", "## Failing tests (first 20 per lane)", ""]
        for r in fails:
            L += [f"**Lane {r['lane']}**", ""] + [f"- `{t}`" for t in r["failed_tests"]] + [""]
    L.append("")
    return "\n".join(L)


def save(results, out_dir: pathlib.Path, python_version: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "BUILD_VERIFICATION.md").write_text(render(results, python_version))
    (out_dir / "build_verification.json").write_text(json.dumps(
        [{k: v for k, v in r.items() if k != "log"} for r in results], indent=2))
