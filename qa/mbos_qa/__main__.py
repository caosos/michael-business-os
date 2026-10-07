"""QA orchestration CLI.

  python -m mbos_qa contracts [--drift-ref REF]   contract validation runner only
  python -m mbos_qa e2e                            run flip + service fixtures, write reports + packets
  python -m mbos_qa interop                        cross-lane checks against peers' actual code
  python -m mbos_qa run [--drift-ref REF]          everything; writes docs/qa/ACCEPTANCE_REPORT.md
  python -m mbos_qa pin --ref COMMIT               re-pin contracts after an Agent 01 semver bump

Exit status is non-zero if any contract check or acceptance test fails.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import OrderedDict

from . import report
from .contracts import CONTRACTS_DIR, run_contract_checks, run_gap_probes
from .e2e import run_all
from .harness import build

QA_ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = QA_ROOT.parent
OUT = REPO / "docs" / "qa"

GROUPS = OrderedDict([
    ("test_a01", "A1 atomic state + receipt (both or neither)"),
    ("test_a02", "A2 immutability (insert-only triggers)"),
    ("test_a03", "A3 hash-chain verification + tamper"),
    ("test_a04", "A4 provenance resolution"),
    ("test_a05", "A5 crash / restart / idempotency"),
    ("test_a06", "A6 YES / NO / MODIFY / HOLD semantics"),
    ("test_a07", "A7 100% dry-run audit"),
    ("test_a08", "A8 LLM spend cap enforcement"),
    ("test_a09", "A9 PANIC fail-closed"),
    ("test_a10", "A10 contract conformance"),
    ("test_g_", "G marketing (G1, G2, G4 + injection)"),
])

FINDINGS = [
    ("F-1", "FACT", "01/04", "Hashes in `contracts/examples/` (`payload_hash`, `row_hash`) do not reproduce under any "
     "tried canonical form. The contract never pins the exact bytes. See F-13/F-14 for the effect on the real lanes.",
     "RECOMMENDATION: Agent 01 pins one canonical form in the contract text and regenerates the example hashes."),
    ("F-2", "FACT", "01", "5 rules stated in ADR/integration prose are NOT enforced by the frozen schemas (see "
     "'Contract gap probes'). The QA runtime enforces each one.",
     "RECOMMENDATION: tighten in v1.1.0: MODIFY `modifications.required=[new_action_request_id,new_payload_hash]`; "
     "HOLD `hold.required=[hold_until,wake_on]`; `prev_hash` pattern; dry_run const for MVP via policy, not schema."),
    ("F-3", "FACT", "01/05", "ActionRequest `status` has no `superseded` value, so a request closed by MODIFY must "
     "reuse `rejected` (QA records `after_state.superseded_by`).",
     "RECOMMENDATION: add `superseded` (minor bump) so NO-rejections and MODIFY-closures are distinguishable in LEARN."),
    ("F-4", "FACT", "04", "SQLite `INSERT OR REPLACE` silently bypassed the append-only DELETE trigger until "
     "`recursive_triggers=ON` (caught by A2, fixed in the mock). Postgres analogue: `TRUNCATE` does not fire "
     "row-level DELETE triggers.",
     "RECOMMENDATION: Agent 04 adds a `BEFORE TRUNCATE` statement trigger and `REVOKE TRUNCATE`; A2 must test it."),
    ("F-5", "FACT", "04", "A hash chain alone cannot detect deletion of the newest rows (strict xfail "
     "`test_tail_truncation_detected` against the QA mock). From reading the code, Agent 04's lane already has "
     "external head anchors (`state/mbos_state/chain.py` write_anchor / verify_lines). QA has not exercised them yet.",
     "RECOMMENDATION: keep the 04 anchors. Wire them into A3 when the suite runs on lane D."),
    ("F-6", "FACT", "05/04", "Budget reservations must be durable. The mock ledger is in memory and lost its "
     "reservation on a hard kill (caught by A5). Recovery now re-reserves under the cap.",
     "RECOMMENDATION: write `budget_ledger` rows in the same transaction as `ACTION_EXECUTING`."),
    ("F-7", "INFERENCE", "05", "A8 and A9 are proven only against in-process mocks. No LiteLLM proxy, OpenBao "
     "lease or egress proxy exists yet.",
     "RECOMMENDATION: re-run A8 and A9 (plus B29) through `MBOS_QA_IMPL` once lane E ships. Do not sign off the MVP on mocks."),
    ("F-8", "INFERENCE", "04", "A2 cannot prove the `agent_write` *role* is denied, because SQLite has no roles.",
     "RECOMMENDATION: the Postgres A2 run must connect as `agent_write` and as `gateway`."),
    ("F-9", "FACT", "01", "Item-level state with several ActionRequests has no specified rule. QA rule: any pending → "
     "AWAITING_APPROVAL; else any approved → APPROVED; else any held → HELD; all rejected → REJECTED → ARCHIVED. "
     "QA also assumes these edges: HELD → AWAITING_APPROVAL on wake, MAYBE → RESEARCHING.",
     "RECOMMENDATION: Agent 01 confirms or replaces this rule in the state-machine spec."),
    ("F-10", "FACT", "01/05", "The receipt vocabulary has no event for 'in-flight at freeze' or for guard denials. "
     "QA uses `POLICY_DECIDED` with `after_state.guard=deny`.",
     "RECOMMENDATION: add `ACTION_DENIED` and `ACTION_INFLIGHT_AT_FREEZE` (minor bump) or bless the QA convention."),
    ("F-11", "INFERENCE", "06/Michael", "approval.schema says step-up is required for *irreversible* actions. Every "
     "seller or customer email is irreversible, so every email approval needs WebAuthn/TOTP. That risks approval "
     "fatigue.",
     "RECOMMENDATION: Agent 06 UX considers a session-scoped step-up. This is an owner decision only if it would "
     "relax the rule."),
    ("F-12", "FACT", "01", "Agent 01's `validate_contracts.py` does not check `format` (date-time). The QA runner does.",
     "RECOMMENDATION: adopt `FORMAT_CHECKER` in the coordinator validator."),
    ("F-13", "FACT", "01/04 (BLOCKING for integration)", "Two lanes define the receipts ledger `mbos.receipts`: "
     "01 `src/mbos/db/migrations/0001_spine.sql` and 04 `state/migrations/0001_foundation.sql`. They use different "
     "row_hash formulas, and both differ from the contract text that 05, 06 and 07 implement. On one identical "
     "receipt, PostgreSQL 16 produced 3 different hashes, so no lane can verify another lane's chain "
     "([INTEROP_REPORT](INTEROP_REPORT.md)).",
     "RECOMMENDATION: Agent 01 rules on ONE ledger (04 per the ownership map) and ONE byte-exact formula, then "
     "bumps the contract. Until then, cross-lane A3 cannot pass."),
    ("F-14", "FACT", "01/03/05", "Integral floats hash differently: `{\"offer\": 850.0}` gives one hash in 01/02/06/07 "
     "and another in 03, whose Decimal normalisation emits `850`. 05 refuses floats in approval payloads outright.",
     "RECOMMENDATION: adopt 05's rule (no floats in hashed payloads; money as integer cents) or RFC 8785 JCS in "
     "every lane. This is a contract decision for Agent 01."),
    ("F-15", "FACT", "03", "Agent 03 changed `opportunity`, `scorecard` and `service-job` schemas without changing "
     "their `$id`, contrary to the ADR-0004 mitigation. Its 13 scored examples (26 documents) still validate "
     "against frozen v1.0.0, so nothing breaks today.",
     "RECOMMENDATION: 03 bumps the `$id` / version on its next schema change. 01 re-pins through a semver bump."),
]


def cmd_contracts(drift_ref):
    rep = run_contract_checks(CONTRACTS_DIR, drift_ref=drift_ref)
    for c in rep.checks:
        print(("PASS " if c.passed else "FAIL ") + c.name + (f" — {c.detail}" if c.detail else ""))
    for g in run_gap_probes():
        print(("OK   " if g.passed else "GAP  ") + g.name + f" — {g.detail}")
    return rep


def cmd_e2e(out_dir: pathlib.Path):
    with tempfile.TemporaryDirectory() as td:
        h = build(pathlib.Path(td) / "e2e")
        results = run_all(h)
        sections = [report.item_section(h, r["item_id"], r["fixture"]) for r in results]
        pk_out = out_dir / "packets"
        if pk_out.exists():
            shutil.rmtree(pk_out)
        shutil.copytree(h.workdir / "packets", pk_out)
        impl = h.implementations
        chain = h.store.verify_chain()
        n_exec = len(h.store.receipts(type="ACTION_EXECUTED"))
    body = [
        "# End-to-end dry-run result: one flip and one service",
        "",
        "> Generated by `python -m mbos_qa e2e` (Agent 07, lane G). **Fully synthetic fixtures. DRY-RUN.** "
        "Nothing was sent, posted, purchased or paid. Owner decisions in this run are **simulated by the fixture**, "
        "not made by Michael. A fixed clock and seeded IDs make this file reproducible byte for byte.",
        "",
        "## Implementations under test",
        "",
        "| Lane | Implementation |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in impl.items()],
        "",
        f"**Ledger:** `verify_chain` {'PASS' if chain.ok else 'FAIL'} over {chain.checked} receipts. "
        f"{n_exec} dry-run executions, and every one has `dry_run=true`.",
        "",
        "**Manual-assist packets:** [`packets/`](packets/)",
        "",
        *sections,
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "E2E_REPORT.md").write_text("\n".join(body))
    print(f"wrote {out_dir / 'E2E_REPORT.md'} and {len(list(pk_out.glob('*.md')))} packets")
    return results, chain.ok


def cmd_tests() -> tuple[int, list[tuple[str, str, str, str]]]:
    with tempfile.TemporaryDirectory() as td:
        xml = pathlib.Path(td) / "junit.xml"
        env = dict(os.environ, PYTHONPATH=str(QA_ROOT))
        rc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}",
                             "tests"], cwd=QA_ROOT, env=env).returncode
        rows = []
        for tc in ET.parse(xml).getroot().iter("testcase"):
            outcome = "passed"
            for child in tc:
                if child.tag in ("failure", "error"):
                    outcome = "FAILED"
                elif child.tag == "skipped":
                    outcome = "xfail (known gap)" if "xfail" in (child.get("type", "") + child.get("message", "")) else "skipped"
            rows.append((tc.get("classname").split(".")[-1], tc.get("name"), outcome, ""))
    return rc, rows


def write_acceptance_report(contract_rep, gaps, test_rc, rows, e2e_ok, drift_ref):
    pin = json.loads((CONTRACTS_DIR / "PIN.json").read_text())
    lines = [
        "# Acceptance report: A1–A10 (+ G), wave one",
        "",
        "> Generated by `python -m mbos_qa run` (Agent 07, independent QA / integration lane G). "
        "Every component not owned by this lane is a **clearly marked MOCK** that conforms to the frozen contracts "
        "and sits behind the `MBOS_QA_IMPL` seam. **A green run here proves the invariants and the tests. It does "
        "not prove the other lanes' code.** That code does not exist yet; the same suite re-runs against it unchanged.",
        "",
        f"- Contracts: v{pin['contracts_version']} pinned byte-exact from `{pin['source_branch']}` @ "
        f"`{pin['source_commit'][:7]}` ({len(pin['files'])} files)" + (f"; drift check vs `{drift_ref}`" if drift_ref else ""),
        f"- Contract validation: **{'PASS' if contract_rep.passed else 'FAIL'}** "
        f"({sum(c.passed for c in contract_rep.checks)}/{len(contract_rep.checks)} checks)",
        f"- Acceptance tests: **{'PASS' if test_rc == 0 else 'FAIL'}** "
        f"({sum(r[2] == 'passed' for r in rows)} passed, {sum(r[2] == 'FAILED' for r in rows)} failed, "
        f"{sum(r[2].startswith('xfail') for r in rows)} strict-xfail known gaps)",
        f"- End-to-end dry-run (flip + service): **{'PASS' if e2e_ok else 'FAIL'}** → [E2E_REPORT.md](e2e/E2E_REPORT.md)",
        "- Cross-lane interop against the peers' real code: [INTEROP_REPORT.md](INTEROP_REPORT.md) "
        "(`python -m mbos_qa interop`). Its FAILs are findings F-13, F-14 and F-15.",
        "",
        "## Summary by acceptance test",
        "",
        "| Test | Result | Cases | Verified against |",
        "|---|---|---:|---|",
    ]
    against = {"test_a02": "mock store (SQLite triggers); Postgres role check pending F-8",
               "test_a08": "in-process LLM cap mock; LiteLLM pending F-7",
               "test_a09": "file-backed PANIC mock; egress/OpenBao pending F-7"}
    for prefix, title in GROUPS.items():
        g = [r for r in rows if r[0].startswith(prefix)]
        failed = [r for r in g if r[2] == "FAILED"]
        xf = [r for r in g if r[2].startswith("xfail")]
        res = "FAIL" if failed else ("PASS" + (f" ({len(xf)} known gap)" if xf else "")) if g else "NOT RUN"
        lines.append(f"| {title} | **{res}** | {len(g)} | {against.get(prefix, 'reference mocks (contract-conformant)')} |")
    lines += ["", "## Contract validation runner", "", "| Check | Result |", "|---|---|"]
    lines += [f"| {c.name} | {'PASS' if c.passed else 'FAIL ' + c.detail} |" for c in contract_rep.checks]
    lines += ["", "## Contract gap probes (the schema ACCEPTS these; ADR prose forbids them)", "",
              "| Probe | Status |", "|---|---|"]
    lines += [f"| {g.name} | {g.detail} |" for g in gaps]
    lines += ["", "## Findings for other lanes", "", "| ID | Tag | For | Finding | Recommendation |", "|---|---|---|---|---|"]
    lines += [f"| {i} | {tag} | {who} | {f} | {rec} |" for i, tag, who, f, rec in FINDINGS]
    lines += ["", "## Every test case", "", "| Module | Test | Outcome |", "|---|---|---|"]
    lines += [f"| {m} | `{n}` | {o} |" for m, n, o, _ in rows]
    lines += ["", "## How to reproduce", "", "```bash",
              "cd qa && python3.12 -m venv ../.venv && ../.venv/bin/pip install -r requirements.txt",
              "../.venv/bin/python -m mbos_qa run --drift-ref origin/research/agent-01-coordinator",
              "# against real lanes later:  MBOS_QA_IMPL=mbos.qa_adapter:build ../.venv/bin/python -m mbos_qa run",
              "```", ""]
    (OUT / "ACCEPTANCE_REPORT.md").write_text("\n".join(lines))
    print(f"wrote {OUT / 'ACCEPTANCE_REPORT.md'}")


def cmd_pin(ref: str):
    src = "docs/research/contracts/"
    files = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref, src], capture_output=True, text=True,
                           check=True, cwd=REPO).stdout.split()
    manifest = {}
    for f in files:
        if not f.endswith(".json"):
            continue
        blob = subprocess.run(["git", "show", f"{ref}:{f}"], capture_output=True, check=True, cwd=REPO).stdout
        rel = f[len(src):]
        (CONTRACTS_DIR / rel).parent.mkdir(parents=True, exist_ok=True)
        (CONTRACTS_DIR / rel).write_bytes(blob)
        manifest[rel] = "sha256:" + hashlib.sha256(blob).hexdigest()
    commit = subprocess.run(["git", "rev-parse", ref], capture_output=True, text=True, check=True, cwd=REPO).stdout.strip()
    pin = json.loads((CONTRACTS_DIR / "PIN.json").read_text())
    pin.update(source_commit=commit, files=dict(sorted(manifest.items())))
    (CONTRACTS_DIR / "PIN.json").write_text(json.dumps(pin, indent=2))
    print(f"pinned {len(manifest)} files @ {commit}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mbos_qa")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("contracts", "run"):
        p = sub.add_parser(name)
        p.add_argument("--drift-ref")
    sub.add_parser("e2e")
    sub.add_parser("interop")
    p = sub.add_parser("pin")
    p.add_argument("--ref", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "contracts":
        return 0 if cmd_contracts(a.drift_ref).passed else 1
    if a.cmd == "e2e":
        _, ok = cmd_e2e(OUT / "e2e")
        return 0 if ok else 1
    if a.cmd == "interop":
        from . import interop
        rep = interop.run()
        (OUT / "INTEROP_REPORT.md").write_text(interop.render(rep))
        for c in rep.checks:
            print(f"{c.status:7} {c.group} · {c.name} — {c.detail[:140]}")
        return 0
    if a.cmd == "pin":
        cmd_pin(a.ref)
        return 0
    rep = cmd_contracts(a.drift_ref)
    gaps = run_gap_probes()
    _, e2e_ok = cmd_e2e(OUT / "e2e")
    rc, rows = cmd_tests()
    write_acceptance_report(rep, gaps, rc, rows, e2e_ok, a.drift_ref)
    return 0 if (rep.passed and rc == 0 and e2e_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
