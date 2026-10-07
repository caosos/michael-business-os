# Agent Status

- **Agent:** 01
- **Role:** Chief Coordinator / Core Platform / Integration (Lane A)
- **Branch:** `research/agent-01-coordinator`
- **Worktree:** `/home/michaelos/business-os-worktrees/agent-01-coordinator`
- **State:** WAITING
- **Current phase:** ROUND TWO. The Lane A spine is built and tested. Integration rulings R1–R11 are issued.
- **Waiting on:** Agent 04 migration `0005` (integration ruling R1), the critical path to porting the spine onto the canonical state schema.
- **Started:** 2026-10-06
- **Last updated:** 2026-10-07

## Current objective
Build the durable application spine DISCOVER → NORMALIZE → SCORE → RECOMMEND → APPROVE → DRY-RUN ACT → RECEIPT and integrate the specialist lanes. All external actions are DRY-RUN only.

## Completed in round two
- **Python 3.12 project `mbos`.** Project-local toolchain (uv, `.venv`; no sudo, no system packages). PostgreSQL 16.2 for dev and tests via the `pgserver` wheel.
- **Pydantic v2 models aligned 1:1 with the frozen contracts v1.0.0** (`src/mbos/contracts/`).
  - Construction validates against the frozen JSON Schemas.
  - All 7 frozen examples round-trip byte-equal.
  - Drift tests fail on any field mismatch.
- **Postgres spine** (`src/mbos/db/migrations/0001_spine.sql`, `0002_dedup_blocking_key.sql`). Enforced in the DB:
  - insert-only ledgers
  - hash-chained receipts under one lock
  - no receipt without existing provenance
  - provenance anyOf rule
  - the Item state machine
  - frozen ActionRequest payloads
  - approvals must match `payload_hash`
  - MVP dry-run-only CHECKs
- **DBOS durable backbone** (`src/mbos/workflows.py`):
  - discover → ingest/dedup → score → recommend → route
  - durable approval gate (YES/NO/MODIFY/HOLD, with HOLD re-notify, wake and escalate, and no auto-execution)
  - gateway → dry-run effector → receipt
  - exactly-once datasource transactions and recovery on launch
- **Lane interfaces** (`src/mbos/interfaces.py`): SourceAdapter, Normalizer, Deduper, Scorer, ActionPlanner, PolicyDecisionPoint, Gateway, Effector, KillSwitch, LLMBudget, Notifier. Labelled reference stubs live in `src/mbos/reference/`.
- **Agent 03's REAL engine wired in** behind `Scorer` (`src/mbos/adapters/economics.py`), installed from `dcd6883` without a merge.
- **Operator CLI `mbos`:** devdb, migrate, worker, queue, show, decide (`--seen` hash, `--step-up`), ping, outcome, panic, audit.
- **`RUNBOOK.md`.**
- **Integration review of all six specialist branches.** Rulings R1–R11 are in `docs/integration/ROUND_TWO_INTEGRATION.md`.
- **ADRs:** ADR-0009 (contracts v1.1.0) is PROPOSED and NOT applied. The registry has round-two dispositions.

## Test results (FACT; run on this branch)
- Command: `.venv/bin/python -m pytest -q`
- Result: **111 passed, 0 failed** (about 77 s).
  - A1–A10 acceptance: all pass. A5 uses a real `os._exit` crash and restart; A6 includes a hard-restart HOLD.
  - Unit tests: contract alignment, state-machine parity, `validate_contracts.py`, protocol conformance, scorer replay.
  - Integration tests: lane-C engine in the workflow, blocking-key dedup, step-up, MODIFY by full payload.
- Honest scope limits:
  - **A8** is enforced by the spine ledger, not yet by LiteLLM keys (lane E).
  - **A9** covers the gateway fail-closed part only. Egress cut and lease revocation are lane E.
  - The store is the reference DDL until the R1 port.

## Findings
- FACT: all six lanes keep byte-identical copies of the frozen contracts. There is no drift.
- FACT: Agent 03's 13 golden outputs validate against frozen v1.0.0, so re-vendoring is optional.
- FACT: `examples/action-request-email-held.example.json` has a `payload_hash` that does not reproduce. The fix is proposed in ADR-0009.
- FACT: there are three receipt-hash formulas (01, 04, 05), and 05 and 06 each keep a second ledger in SQLite. Ruled under R2: one chain, using 04's formula.
- FACT: Agent 02's `dedup_key` is a blocking bucket. The spine's earlier UNIQUE(dedup_key) would have merged distinct listings. Fixed (R8).
- INFERENCE: real discovered Items (02) carry no `economics`, so they will park in RESEARCHING until a RESEARCH/estimate producer exists (03 + 02). This is safe and correct.

## Decisions made (coordinator, technical)
R1–R11 in `docs/integration/ROUND_TWO_INTEGRATION.md`:
- 04's schema is canonical.
- One receipt chain.
- Canonical JSON is normative.
- The gateway owns action-status receipts.
- PANIC state lives in Postgres.
- The PDP gets the full request.
- Agent ids equal branch names, and 05 grants propose-only to `agent-01-coordinator`.
- Blocking-key dedup.
- An ActionPlanner exists.
- The Operator UI calls `spine.decide`.
- Two acceptance suites, with 01's as the release gate.

## Unknowns
- Volume per source per day (02).
- The DBOS login role and checkpoint schema on 04's roles model.
- Michael's thresholds (MICHAEL_DECISIONS #1/#2). Provisional defaults are in use.

## Blockers
None for Lane A's own work. The next step is WAITING on 04 `0005` (R1).

## Needs Michael decision
None new. MICHAEL_DECISIONS #1–#5 are unchanged; none blocks the dry-run MVP.

## Needs coordinator review
- Specialists' acknowledgement of R1–R11. Objections go in your own `AGENT_STATUS.md` and are scored with the rubric.
- ADR-0009 cross-lane review.

## Files produced (round two)
- `pyproject.toml`, `.gitignore`, `RUNBOOK.md`
- `src/mbos/**`: contracts, db, ledger, spine, workflows, runtime, interfaces, audit, cli, reference/, adapters/
- `tests/**`: acceptance A1–A10, unit, integration, helpers
- `fixtures/sources/illustrative.json`
- `docs/integration/ROUND_TWO_INTEGRATION.md`
- `docs/decisions/ADR-0009-contracts-v1.1.0-proposal.md`
- `docs/decisions/INDEX.md`
- `docs/receipts/2026-10-07-round-two-spine.md`

## Next action
1. On 04's `0005`: port `ledger.py`/`spine.py` onto `mbos_state.StateStore` (R1/R2), with A1–A10 passing unchanged.
2. Wire 05's ActionGateway, PanicState and PDP adapters (R4–R7), with A5/A9 passing on the real gateway.
3. Ship `mbos.qa_adapter:build` for 07 (R11). Then build the B adapter and Deduper with 02.
