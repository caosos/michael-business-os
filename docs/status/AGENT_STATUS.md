# Agent Status

- **Agent:** 01
- **Role:** Chief Coordinator / Core Platform / Integration (Lane A)
- **Branch:** `research/agent-01-coordinator`
- **Worktree:** `/home/michaelos/business-os-worktrees/agent-01-coordinator`
- **State:** CLOSED
- **Done:** A-48 @ COMMIT; A-43 @ da6cf4a; A-44 @ 6440be3; A-42 @ 69402d9; A-41 @ 281cc74; A-40 @ 1160310; A-39 @ 6185927; A-38 @ 2198a74; A-37 @ b92683d
- **Claimed:** A-31 (first bounded worker end to end), A-28 (07's F-50), A-29 (foreman --launch)
- **Done (this wave, runtime migration):** ADR-0014; lanes 02-06 closed out and sessions closed after verification; `tools/worker.py`, `mbos.router`, `mbos.telemetry`; quota from `rate_limit_event` verified; Aria 1945 ack
- **Done (this wave):** A-24, A-25, A-26, A-27, A-12; Aria 1840 ack (ADR-0012, card capital-velocity fields) @ 292adae; Aria 1905 ack (ADR-0013, 20 tasks queued) @ e20d6af; A-23 mission schema @ a704e84 (+ principal_impairment @ 7b42c05); A-22 `tools/foreman.py`; release gate 285 passed (stale lane installs refreshed)
- **Done:** A-00 (ADR-0010), A-01 phase 1 (`Pg04Ledger`), A-07 (`notify_decision`), A-09 (R12), A-11 (interop tool)
- **Current phase:** ROUND TWO. The Lane A spine is built and tested. Integration rulings R1–R11 are issued.
- **Role:** foreman/dispatcher. I own `docs/status/READY_QUEUE.md` and `ACTIVE_WORK.md` (`docs/COORDINATION.md`).
- **Started:** 2026-10-06
- **Last updated:** 2026-10-08

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

## Round two, wave two (2026-10-07)
- **F-13/F-14 ruled (ADR-0010, ACCEPTED).**
  - Canonical JSON is MBOS-CJSON-1, an RFC 8785 profile.
  - Receipt `row_hash` is MBOS-RH-1.
  - Agent 04 is the sole ledger owner.
- Reference implementations are in Python and SQL, with golden vectors. FACT: they agree on PostgreSQL 16.2.
- Interop baseline (`tools/interop_check.py`): every lane differs only on numbers. The conformance tasks are B-02, C-02, D-02, E-01, F-02 and G-01.
- The spine conforms: migration `0003`. Tests: **142 passed, 0 failed**.
- The foreman loop is published: `docs/COORDINATION.md`, `READY_QUEUE.md`, `ACTIVE_WORK.md`, and pointers in START_HERE.md and AGENT_HANDOFF.md.

## Wave two, continued (13:05)
- **F-13 CLOSED.** Lane D's real chain verifies with the pure-Python reference (hard gate in `tests/integration/test_state04_adapter.py`).
- **F-14 CLOSED.** All 6 Python lanes pass 10/10 vectors and 6/6 rejections, with byte-identical vendored copies.
- New rulings:
  - R12: lane D's strict edge table is canonical; D-05 removes the accommodated edges.
  - R13: a PASS resting only on priors goes to RESEARCHING.
- **Provenance correction:** every one of my Round Two commits up to `bf215b2` was recorded as "Agent 07 Marketing" because of the shared git config.
  - The correction-of-record receipt is pushed.
  - All commits since `c5c7c1c` use an explicit identity.
  - X-01 (the launcher fix) is an operator item.
- Tests: 146 passed, 1 xfailed (the deliberate D-05 gate), plus the lane-D integration suite.

## 17:30 checkpoint (session paused: usage limit)
- DONE this wave:
  - A-03: 05's real gateway behind the spine on lane D
  - A-02: release gate **PASS 5/5** (docs/status/RELEASE_GATE.md)
  - A-05, A-13, A-14, A-16, A-17
  - A-01 milestones 1+2
- Tests: 158 passed.
- Next for 01:
  - adopt D-15 provision in the lane-D tests and finish A1–A10 parity on lane D (A-01)
  - A-18 (PANIC + reconcile via 05)
  - A-04, A-15, A-12, A-10, A-06

## Deal Sniffer opportunity card (A-19, DONE 2026-10-07 18:10)
- Michael's spec is implemented as ADR-0011 plus `card.schema.json` (a new additive contract; frozen v1.0.0 untouched). `mbos.card` builds it, `mbos card ITEM` prints it.
- It is a derived view of the Item, its receipts and lane enrichment, never a source of truth. Honesty rule: every datum has a basis or is UNKNOWN, and the card lists its UNKNOWN paths.
- Includes:
  - recommendation CONTACT/OFFER/BUY/COUNTER/HOLD/PASS with the reason and a waiting flag
  - the status timeline from real receipts, with no invented stages
  - the full activity trail (who, what, why, inputs, result, receipt, next action)
  - logistics from the operator profile data (trailer not owned, borrowed possible, never auto-rejected; borrowed trailer must be confirmed)
- A lint rejects elementary mechanic advice unless sourced and model-specific.
- Lanes attach enrichment through `spine.record_enrichment`, with no contract change.
- Tests: 177 passed. Cards validate on the lane D/E end-to-end run.
- Open, by design, for the lanes: B-15 (listing and seller blocks), C-15/C-16 (economics ranges, logistics, seasonality, value-add), F-13 (rendering), G-05 (acceptance), E-12, D-16.
- NEGOTIATING and QUALIFIED are not shown until inbound communication events exist (ADR-0009 item 11).

## 19:00 checkpoint (card wiring + release candidate)
- A-20 DONE: an `Enricher` protocol; lane C's `EconomicsEnricher` (economics/logistics/seasonality/why/value_add) and lane B's `LaneBEnricher` run in the workflow after ingest and after scoring.
  - Enrichment is atomic and idempotent (lost-update bug found by 04 fixed).
  - Lane C skips placeholder-scored items rather than crash.
- A-10 DONE: contracts and operator profile ship in the wheel.
- R21 (F-23): a policy-denied proposal leaves the item RECOMMENDED, notifies Michael, and the card recommends HOLD.
- R22 (F-25): A5 means never duplicate and settle truthfully; E-13 queued to 05.
- G-04 verdict from 07 is **NOT READY**. Open items and owners:
  - F-24 (05): confirm the guard denial leaves no stale approval, including unreadable and corrupt PANIC states.
  - F-25 (05): durable provider lookup.
  - F-22 (05): propose-only publish grant.
  - F-23 (01): fixed.
  - 07 re-runs as G-06 after E-13.
- Tests: 183 passed.

## 22:30 checkpoint (card hardening from 07's adversarial acceptance)
- 07's G-05 found 87 failures in `mbos.card`, all mapped to findings. Fixed F-26..F-38 in one pass:
  - validated lane data (shape AND value) with UNKNOWN on any failure, so malformed enrichment never crashes the card
  - control, ANSI and bidi text is cleaned, and NUL is scrubbed at ingest with one bad listing dropped by a savepoint, not the batch
  - a dry-run send is labelled and does not "wait for the seller"
  - outcomes close a card only if their kind closes it
  - stage mapping falls back to intent text
  - deterministic request order and filtered receipts
  - `card_hash` is verified
  - broader mechanic-advice lint and a checkable-source rule
  - lane reasons are shown only with provenance
  - listing flags are visible
- F-39 kept (Michael's own vocabulary has HOLD). R24: `decide()` consults the PDP's step-up requirement (F-40).
- Open, with owners: E-15 (05: other guard refusals settle failed; narrow agent-01 grants), G-07 (07 re-run), F-14 (06 operator-note form), B-18 (02 flip years flag).
- Tests: 215 passed.

## 00:15 checkpoint: RELEASE CANDIDATE READY (dry-run scope)
- 07's G-07: 105 passed, 0 failed on the lane D + lane E stack at `2d4e8dd`. Card acceptance 232/11, and I fixed the remaining five (F-36 per-record isolation, F-30, F-28, F-31, F-27).
- My release gate passes 6/6 (docs/status/RELEASE_GATE.md), now including a byte-level check that installed lane packages match their pushed heads.
- Removed 54 committed `build/` files (06 P-06-15; 07's stale-install finding). The packaging test builds in a temp copy.
- `retract_operator_note` added (human channel).
- READY covers the dry-run scope only. It does NOT cover live providers, the LiteLLM cap at the proxy, a real egress cut, real sources, or live sends. Those need Michael's items in `docs/status/OWNER_ACTIONS.md`.
- Open: E-16 (05), X-03 (all lanes), F-11/A-15 (follow-up API), A-04 (post-discover wiring of 02), A-12, A-06 (ADR-0009 decision).

## Next action (superseded by READY_QUEUE.md)
1. On 04's `0005`: port `ledger.py`/`spine.py` onto `mbos_state.StateStore` (R1/R2), with A1–A10 passing unchanged.
2. Wire 05's ActionGateway, PanicState and PDP adapters (R4–R7), with A5/A9 passing on the real gateway.
3. Ship `mbos.qa_adapter:build` for 07 (R11). Then build the B adapter and Deduper with 02.
