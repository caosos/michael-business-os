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
| `tests/` | A1–A10 + G acceptance suite (pytest). Includes a real hard-kill crash test (`os._exit(137)` in a child process). |

## Run

```bash
python3.12 -m venv ../.venv && ../.venv/bin/pip install -r requirements.txt
../.venv/bin/python -m mbos_qa run --drift-ref origin/research/agent-01-coordinator
```

This writes `docs/qa/ACCEPTANCE_REPORT.md`, `docs/qa/e2e/E2E_REPORT.md` and `docs/qa/e2e/packets/`.
The e2e output is reproducible byte for byte (fixed clock, seeded IDs).

## Plugging in a real lane

Lane A exposes `build(workdir, *, mode, seed, clock, fresh) -> Harness`, with the same attributes as
`mbos_qa.harness.Harness`, and wires in its real store, gateway and workflow. Then:
`MBOS_QA_IMPL=mbos.qa_adapter:build python -m mbos_qa run`. Mock-only checks (A2 roles, A8 LiteLLM,
A9 egress) are listed as findings F-7/F-8 and must be re-run against the real components before MVP sign-off.

## Rules for this suite

- Never weaken a test to make it pass. A test that encodes a real gap is a strict `xfail` with a finding ID.
- Every component that is not this lane's is a mock, and is labelled as one in code and in every report.
- Owner decisions in fixtures are **simulated**. They are labelled `[SIMULATED by QA fixture]` in receipts,
  provenance and packets.
