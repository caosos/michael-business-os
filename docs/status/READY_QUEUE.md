# READY QUEUE: Michael Business OS, Round Two

- **Owner:** Agent 01 (coordinator / dispatcher). **Protocol:** `docs/COORDINATION.md`. Read it before claiming.
- **Last synced:** 2026-10-07 12:10 -0500, against branch heads 02 `6f84127` · 03 `b923852` · 04 `7f0649a` · 05 `bd5aa3d` · 06 `6129cf5` · 07 `6fcaf98`.
- **Read it from any worktree:** `git fetch -q origin && git show origin/research/agent-01-coordinator:docs/status/READY_QUEUE.md`
- **Status values:** READY · CLAIMED · BLOCKED · DONE.
- **Priority:** P0 = critical path · P1 = next-up · P2 = useful parallel work.
- **Every task is DRY-RUN ONLY.** No action without a receipt, and no receipt without provenance.

## Critical path
`D-01` (04: migration 0005) and `D-02` (04: ADR-0010 ledger) → `A-01` phase 2 (01: spine on 04's store) → `E-02` (05: gateway on Postgres) → `A-03` (01: real gateway wired) → `G-02` (07: release run on real components).

## Tasks

### Lane A: Agent 01 (core / integration)
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| A-00 | P0 | F-13/F-14 rulings: ADR-0010, reference implementations (py and sql), vectors, interop tool, spine conformance | none | **DONE** | 01 | 142 tests pass; vectors pass in Python and in PostgreSQL 16 |
| A-01 | P0 | Port `ledger.py`/`spine.py` onto 04's `StateStore` (R1/R2). **Phase 1, now:** state adapter against 04's existing SQL API @ `7f0649a`. **Phase 2:** on 0005 | D-01, D-02 for phase 2 | **CLAIMED** | 01 | A1–A10 pass unchanged on 04's schema |
| A-02 | P1 | Release gate `tools/release_gate.sh` (pytest + interop_check + `mbos audit` + contract validator), plus `docs/status/RELEASE_GATE.md` with results | none | READY | 01 | One command, non-zero on any failure, results committed |
| A-03 | P1 | Wire 05 `ActionGateway`/`PanicState`/`policy.decide` behind `Gateway`/`KillSwitch`/`PDP`. The gateway owns action-status receipts (R4) | E-02 | BLOCKED | 01 | A5 and A9 pass with 05's real gateway |
| A-04 | P2 | Wire 02's B adapter + Deduper into `Components`; end-to-end fixture discovery → RESEARCHING | B-01 | BLOCKED | 01 | Integration test: 02 fixtures through the DBOS workflow |
| A-05 | P2 | Wire 03's RESEARCH producer as a workflow step (RESEARCHING → SCORED) | C-01 | BLOCKED | 01 | A real discovered Item advances past RESEARCHING in a test |
| A-06 | P2 | ADR-0009 v1.1.0: collect lane acknowledgements, then decide | lane acks | READY | 01 | ADR-0009 ACCEPTED or amended; vectors and examples regenerated |

### Lane D: Agent 04 (state, CRITICAL PATH)
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| D-01 | **P0** | Migration `0005`: `effector_calls` (UNIQUE idempotency_key, CHECK dry_run), PANIC/governance state table (R5), `llm_spend`, `artifacts` (sha256 content-addressed), all insert-only where they are ledgers. Answer: DBOS login role (`mbos_dbos`), and whether datasource checkpoints may live in schema `dbos` of the app DB | none | **CLAIMED** | 04 | Tables exist with the same invariants as 01's `0001_spine.sql`; answers in AGENT_STATUS |
| D-02 | **P0** | **ADR-0010 conformance (supersedes the R3 wording in your claim).** Install `contracts/canonical/mbos_canonical.sql`. Set `NEW.canonical := mbos.cjson(mbos.receipt_canonical(NEW))` and `NEW.row_hash := 'sha256:'∥sha256(canonical)`; `verify_chain` uses the same formula. `mbos.payload_hash` → `mbos.cjson_sha256`. Keep `utc_iso` (it already conforms) | none | **CLAIMED** (part of 04's active claim) | 04 | All `vectors.json` pass in PostgreSQL; a chain exported from 04's DB verifies with `mbos_canonical.verify_chain` |
| D-03 | P1 | Reporting views (pipeline by lane, HOLD backlog, approval latency) over the ADR-0010 chain; restore drill D1 then `verify_chain` | D-01 | READY after D-01 | 04 | D1 passes; views documented |

### Lane B: Agent 02 (discovery)
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| B-01 | P1 | `SourceAdapter`/`Normalizer`/`Deduper` against `mbos.interfaces` (R8). `raw_ref` = hash of stored raw bytes. `FetchResult.error`/`freeze_requests` go to a side channel | none | **CLAIMED** | 02 | 02's fixtures run through `mbos` `Components` in 02's tests; identity-first dedup |
| B-02 | P1 | ADR-0010: `ids.canonical_json` → reference `mbos_canonical` | none | READY | 02 | `tools/interop_check.py` row 02 = 10/10 |
| B-03 | P2 | Credential-free sources: GSA Auctions API, then Trash Nothing, as fixture-first adapters, read-only, honouring ADR-02-0202 | B-01 | READY after B-01 | 02 | Fixture tests; no live calls without explicit enablement |
| B-04 | P2 | Source-health → L2 freeze request shape, agreed with 05 (`discovery.source.<src>.read`) | E-01 | READY | 02 (+05) | A shared fixture both lanes test against |

### Lane C: Agent 03 (economics)
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| C-01 | P1 | RESEARCH/estimate producer: fills `Item.economics` from normalized fields and comps evidence, with provenance per estimate (FACT/INFERENCE tags), deterministic | none | **CLAIMED** | 03 | An Item from 02's fixtures gets valid economics and scores past MAYBE-for-missing-inputs |
| C-02 | P1 | ADR-0010: `canonical.py` → reference (Decimals hashed as doubles); re-baseline golden hashes with a note | none | READY | 03 | interop row 03 = 10/10; 13 goldens replay |
| C-03 | P2 | ADR-03-002 is ACCEPTED-WITH-CHANGES (see INDEX). Give the v1.1.0 schemas versioned `$id`s for re-vendoring (ADR-0009 item 6) | none | READY | 03 | New `$id`s; 03's tests pass |

### Lane E: Agent 05 (governance)
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| E-01 | P1 | R7 propose-only grant for `agent-01-coordinator` + ADR-0010 `payload_hash` (drop the float refusal) + stand-in store `row_hash` → MBOS-RH-1 | none | **CLAIMED** | 05 | interop row 05 = 10/10; `vectors.json` `receipt_chain` verifies with 05's code |
| E-02 | P0 (after D-01) | Postgres-backed `GovernanceStore` + `PanicStore` on 04's tables (R2/R4/R5). Fail-closed is kept | D-01, D-02 | BLOCKED | 05 | 05's suite passes on Postgres; no SQLite in the production path |
| E-03 | P2 | A8/A9 hardening, dry: per-agent LiteLLM budget config generator (no external calls); L3 hook that cancels unstarted DBOS workflows (`DBOS.cancel_workflows`) and writes the egress deny-all policy file | none | READY | 05 | Tests prove L3 cancels pending workflows and emits deny-all config; nothing reaches the network |

### Lane F: Agent 06 (Operator UI)
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| F-01 | P1 | R10: Operator UI on `spine.pending_decisions` / `spine.decide(channel="web", new_payload=…, hold=…, auth_context={"step_up":…})` + `notify_decision`; drop the UI gateway, ticker and SQLite store | none | **CLAIMED** | 06 | A YES/NO/MODIFY/HOLD web flow against 01's spine on Postgres (pgserver) |
| F-02 | P1 | ADR-0010: `util.canonical_json` → reference; stand-in `row_hash` → MBOS-RH-1 | none | READY | 06 | interop row 06 = 10/10 |
| F-03 | P2 | Comms dry-run spec items (1)(3)(4)(6) from 06's status: templates registry, rate/consent rules as data | none | READY | 06 | Data files + tests; no sends |

### Lane G: Agent 07 (QA)
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| G-01 | P1 | ADR-0010: `core.canonical`/`receipt_row_hash` → reference; add `vectors.json` to `mbos_qa interop`; re-run interop across all lanes and publish the matrix | none | READY | 07 | Matrix published; F-13/F-14 closed or re-opened with evidence |
| G-02 | P1 | **R11 amended: start now.** 07 writes `MBOS_QA_IMPL` = `mbos_qa.impl_spine:build` against 01's public API (`mbos.runtime`, `mbos.spine`, `mbos.ledger`, `mbos.audit`, `mbos.workflows`) on pgserver Postgres. Re-target the store to 04's schema when A-01 lands | none (A-01 later) | READY | 07 | A1–A10 from `qa/` run against the real spine; results reported as real, not mocked |
| G-03 | P2 | G1–G4 marketing tests against the real ActionRequest/approval path (publishing drafts as dry-run ActionRequests) | G-02 | READY after G-02 | 07 | G1–G4 green on the real spine |

## Michael (business-policy only; nothing blocks the dry-run MVP)
- MICHAEL_DECISIONS #1–#5 are unchanged.
- **Optional:** an eBay developer keyset for live read-only eBay discovery (Agent 02's runbook). Not required; fixture mode runs the same code.
