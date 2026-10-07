# MBOS QA / Integration harness (lane G, Agent 07)

Independent QA lane for Michael Business OS, round two, wave one. **Dry-run only.** Nothing in this
directory can publish, send, spend or contact anyone, and a test enforces that no network-capable module
is imported.

Core law under test: **no action without a receipt; no receipt without provenance.**

## What is here

| Path | What |
|---|---|
| `contracts/` | Byte-exact pinned copy of the FROZEN contracts v1.0.0 (Agent 01 @ `acb6f3b`). `PIN.json` has the sha256 of every file. Do not edit; re-pin with `python -m mbos_qa pin --ref <commit>`. |
| `mbos_qa/contracts.py` | Contract validation runner: pin integrity, drift check vs the coordinator branch, schema validity, examples, 21 negative invariants, and 5 *gap probes* (rules the ADRs state but the schemas do not enforce). |
| `mbos_qa/harness.py` | `build()`, the seam. `MBOS_QA_IMPL=mock` (default) or `pkg.module:build` for real lanes. The tests never change. |
| `mbos_qa/mocks/` | **MOCKS**, one per missing lane, each conforming to the frozen contracts and labelled `IMPLEMENTATION = "MOCK …"`: workflow (A/01), discovery (B/02), economics (C/03), store (D/04), governance (E/05). |
| `mbos_qa/drafts.py`, `mbos_qa/packet.py` | **Real** (this lane): deterministic outbound drafts with G4 provenance, and the dry-run manual-assist packet effector. |
| `mbos_qa/e2e.py`, `fixtures/` | One synthetic flip (trailer, with a planted prompt injection) and one synthetic service lead (drywall, with attribution), run end to end. |
| `mbos_qa/report.py` | Human-readable report per item: source → normalization → economics → recommendation → approval → dry-run action → receipt → provenance. |
| `tests/test_a*.py`, `tests/test_g_*.py` | A1–A10 + G against the **reference mocks** (they exercise mock internals such as SQLite fault hooks). |
| `tests/spec/` | **A1–A10 spec suite against a REAL implementation** (G-02). It is written only against the QA facade, and `MBOS_QA_IMPL=mbos_qa.impl_spine:build` runs it on Agent 01's spine (PostgreSQL 16 + DBOS, pinned in `impl_spine_PIN`). It is not collected in mock mode. |
| `mbos_qa/impl_spine.py`, `_spine_child.py` | The adapter to 01's public API, plus out-of-process crash/restart scenarios. |
| `mbos_qa/interop.py`, `_probe.py` | ADR-0010 interop: each lane's own hasher on `vectors.json`, plus the SQL twins on PostgreSQL. |
| `mbos_qa/buildverify.py` | Runs every lane's own suite from a clean `git archive`. |

## Run

```bash
python3.12 -m venv ../.venv && ../.venv/bin/pip install -r requirements.txt
../.venv/bin/python -m mbos_qa run --drift-ref origin/research/agent-01-coordinator
```

This writes `docs/qa/ACCEPTANCE_REPORT.md`, `docs/qa/e2e/E2E_REPORT.md` and `docs/qa/e2e/packets/`.
The e2e output is reproducible byte for byte (fixed clock, seeded IDs).

## Running against the real system

```bash
../.venv/bin/python -m mbos_qa spine      # A1–A10 spec suite on Agent 01's spine → docs/qa/SPINE_ACCEPTANCE.md
../.venv/bin/python -m mbos_qa interop    # ADR-0010 cross-lane matrix          → docs/qa/INTEROP_REPORT.md
../.venv/bin/python -m mbos_qa builds --workdir /tmp/claude-1001/a07b   # every lane's own suite → docs/qa/BUILD_VERIFICATION.md
```

The spine is installed non-editable from `git archive` at the commit in `impl_spine_PIN`. To re-target, re-install
at the new commit and update the pin. When A-01 phase 2 moves the spine onto Agent 04's store, only the marked
raw-SQL read block in `impl_spine.py` changes; the spec tests do not.

## Rules for this suite

- Never weaken a test to make it pass. A test that encodes a real gap is a strict `xfail` with a finding ID.
- Every component that is not this lane's is a mock, and is labelled as one in code and in every report.
- Owner decisions in fixtures are **simulated**. They are labelled `[SIMULATED by QA fixture]` in receipts,
  provenance and packets.
