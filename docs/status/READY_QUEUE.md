# READY QUEUE: Michael Business OS, Round Two

- **Owner:** Agent 01 (coordinator / dispatcher). **Protocol:** `docs/COORDINATION.md`. Read it before claiming.
- **Last synced:** 2026-10-07 13:00 -0500, against branch heads 02 `41d45a6` · 03 `73a4d32` · 04 `7f0649a` · 05 `16fb86c` · 06 `c125618` · 07 `397101c`.
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
| A-01 | P0 | Port `ledger.py`/`spine.py` onto 04's `StateStore` (R1/R2). **Phase 1, now:** state adapter against 04's existing SQL API @ `7f0649a`. **Phase 2:** on 0005 | D-01, D-02 for phase 2 | **CLAIMED**, phase 2 now (unblocked) | 01 | A1–A10 pass unchanged on 04's schema |
| A-02 | P1 | Release gate `tools/release_gate.sh` (pytest + interop_check + `mbos audit` + contract validator), plus `docs/status/RELEASE_GATE.md` with results | none | READY | 01 | One command, non-zero on any failure, results committed |
| A-03 | P1 | Wire 05 `ActionGateway`/`PanicState`/`policy.decide` behind `Gateway`/`KillSwitch`/`PDP`. The gateway owns action-status receipts (R4) | E-02 | BLOCKED | 01 | A5 and A9 pass with 05's real gateway |
| A-04 | P2 | Wire 02's B adapter + Deduper into `Components`; end-to-end fixture discovery → RESEARCHING | B-01 | **CLAIMED** | 01 | Integration test: 02 fixtures through the DBOS workflow |
| A-05 | P2 | Wire 03's RESEARCH producer as a workflow step (RESEARCHING → SCORED) | C-01 | **CLAIMED** | 01 | A real discovered Item advances past RESEARCHING in a test |
| A-07 | P1 | `notify_decision(item_id, approval_id)` wake helper for the UI and CLI (06 P-06-1) | none | **DONE** (this push) | 01 | `mbos.workflows.notify_decision` exists; F-01 uses it |
| A-08 | P2 | `_approval_gate` acts on `wake_on` = `new_info` / `price_change` / `auction_ending` via a message kind sent by lanes B/C (06 P-06-2) | none | READY | 01 | Test: a HOLD with `wake_on=price_change` wakes on a price-change message, never executes |
| A-09 | P1 | Ruling R12: the Item edge table is lane D's (every item passes RESEARCHING; a YES on HELD re-presents first; LEARNED is terminal; follow-up edge ACTED→AWAITING_APPROVAL). The spine is aligned (migration 0004) | none | **DONE** (this push) | 01 | Parity test against 04's live DB passes |
| A-12 | P2 | R13 routing: PASS with `pass_on_priors` → RESEARCHING, not ARCHIVED | C-05 | BLOCKED | 01 | Test with 03's flag |
| A-13 | P2 | Wire 06's `CommsActionPlanner` (F-05) and comms dry-run `Effector` (F-06) into `Components`; behind 05's gateway once A-03 lands | F-05, F-06 | BLOCKED | 01 | End-to-end dry-run comms receipts graded by 06's audit |
| A-10 | P1 | Ship the contracts as package data so a non-editable install works without `MBOS_CONTRACTS_DIR` (07 P-07-1/F-16) | none | READY | 01 | `pip install .` into a clean venv; the suite passes with no env var |
| A-11 | P1 | ADR-0010 interop: `tools/interop_check.py` covers vectors, rejections and vendored-copy byte identity | none | **DONE** (this push) | 01 | All 6 Python lanes CONFORM (12:50) |
| A-06 | P2 | ADR-0009 v1.1.0: collect lane acknowledgements, then decide | lane acks | READY | 01 | ADR-0009 ACCEPTED or amended; vectors and examples regenerated |

### Lane D: Agent 04 (state, CRITICAL PATH)
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| D-01 | **P0** | Migration `0005`: `effector_calls` (UNIQUE idempotency_key, CHECK dry_run), PANIC/governance state table (R5), `llm_spend`, `artifacts` (sha256 content-addressed), all insert-only where they are ledgers. Answer: DBOS login role (`mbos_dbos`), and whether datasource checkpoints may live in schema `dbos` of the app DB | none | **DONE** @ `a0d1fbe` | 04 | Tables exist with the same invariants as 01's `0001_spine.sql`; answers in AGENT_STATUS |
| D-02 | **P0** | **ADR-0010 conformance (supersedes the R3 wording in your claim).** Install `contracts/canonical/mbos_canonical.sql`. Set `NEW.canonical := mbos.cjson(mbos.receipt_canonical(NEW))` and `NEW.row_hash := 'sha256:'∥sha256(canonical)`; `verify_chain` uses the same formula. `mbos.payload_hash` → `mbos.cjson_sha256`. Keep `utc_iso` (it already conforms) | none | **DONE** @ `a0d1fbe` (verified by 01's gate test) | 04 | All `vectors.json` pass in PostgreSQL; a chain exported from 04's DB verifies with `mbos_canonical.verify_chain` |
| D-04 | **P0** | Fold Lane E's requirements into 0005 (binding input; ruling R5): `origin/research/agent-05-governance:docs/integration/05-requirements-for-04-migration-0005.md`. Covers: `panic_events` (append-only) + `panic_current` view + `panic_set()`, release by approver only, bootstrap FROZEN; `effector_calls` as the execution-claim table; action-status edges `approved→expired`, `approved→failed` and `executing→cancelled_by_freeze`; budget caps per action, daily, global and velocity | D-01 (same migration) | **DONE** @ `a0d1fbe` (panic_state, effector_calls, llm_spend_authorize, put_artifact) | 04 | 05's E-02 port runs on 0005 without workarounds |
| D-05 | **P0** | R12 re-affirmed: remove `NORMALIZED→SCORED`, `HELD→APPROVED` and `LEARNED→ARCHIVED/FAILED` (added in a0d1fbe to accommodate pre-R12 spine). Keep `ACTED→AWAITING_APPROVAL` | none | READY | 04 | 01's `test_r12_item_edges_match_lane_d` XPASSes (then flipped to a hard gate) |
| D-03 | P1 | Reporting views (pipeline by lane, HOLD backlog, approval latency) over the ADR-0010 chain; restore drill D1 then `verify_chain` | D-01 | **CLAIMED** | 04 | D1 passes; views documented |

### Lane B: Agent 02 (discovery)
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| B-01 | P1 | `SourceAdapter`/`Normalizer`/`Deduper` against `mbos.interfaces` (R8). `raw_ref` = hash of stored raw bytes. `FetchResult.error`/`freeze_requests` go to a side channel | none | **DONE** @ `7c9da45` | 02 | 02's fixtures run through `mbos` `Components` in 02's tests; identity-first dedup |
| B-02 | P1 | ADR-0010: `ids.canonical_json` → reference `mbos_canonical` | none | **DONE** @ `cadfdae` | 02 | `tools/interop_check.py` row 02 = 10/10 |
| B-03 | P2 | Credential-free sources: GSA Auctions API, then Trash Nothing, as fixture-first adapters, read-only, honouring ADR-02-0202 | B-01 | **CLAIMED** | 02 | Fixture tests; no live calls without explicit enablement |
| B-04 | P2 | Source-health → L2 freeze request shape, agreed with 05 (`discovery.source.<src>.read`) | E-01 | **CLAIMED** (02; 05's side is ready) | 02 (+05) | A shared fixture both lanes test against |

### Lane C: Agent 03 (economics)
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| C-01 | P1 | RESEARCH/estimate producer: fills `Item.economics` from normalized fields and comps evidence, with provenance per estimate (FACT/INFERENCE tags), deterministic | none | **DONE** @ `42fed5e` | 03 | An Item from 02's fixtures gets valid economics and scores past MAYBE-for-missing-inputs |
| C-02 | P1 | ADR-0010: `canonical.py` → reference (Decimals hashed as doubles); re-baseline golden hashes with a note | none | **DONE** @ `247c036` | 03 | interop row 03 = 10/10; 13 goldens replay |
| C-03 | P2 | ADR-03-002 is ACCEPTED-WITH-CHANGES (see INDEX). Give the v1.1.0 schemas versioned `$id`s for re-vendoring (ADR-0009 item 6) | none | **DONE** @ `22b49e6` | 03 | New `$id`s; 03's tests pass |

| C-04 | P1 | Sold-comps feed (03 P-03-01, lead 03 with 02 for source access): a comps-evidence bundle interface + a fixture-first sold-comps source behind it (read-only, ADR-02-0202 tiers) that `estimate_item` consumes. Real eBay flips stay `insufficient` without it | none | READY | 03 (+02) | A 02-fixture flip with comps advances RESEARCHING → SCORED with FACT-tagged comp provenance |
| C-05 | P2 | R13: scorecard flag `pass_on_priors` when a PASS rests only on non-FACT inputs | none | READY | 03 | Golden test: a priors-only PASS is flagged |

### Lane E: Agent 05 (governance)
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| E-01 | P1 | R7 propose-only grant for `agent-01-coordinator` + ADR-0010 `payload_hash` (drop the float refusal) + stand-in store `row_hash` → MBOS-RH-1 | none | **DONE** @ `df826c3` | 05 | interop row 05 = 10/10; `vectors.json` `receipt_chain` verifies with 05's code |
| E-02 | P0 (after D-01) | Postgres-backed `GovernanceStore` + `PanicStore` on 04's tables (R2/R4/R5). Fail-closed is kept | D-01, D-02 | **READY, P0: switch to it now** (unblocked by D-01/D-02) | 05 | 05's suite passes on Postgres; no SQLite in the production path |
| E-03 | P2 | A8/A9 hardening, dry: per-agent LiteLLM budget config generator (no external calls); L3 hook that cancels unstarted DBOS workflows (`DBOS.cancel_workflows`) and writes the egress deny-all policy file | none | **DONE** @ `e12caa3` | 05 | Tests prove L3 cancels pending workflows and emits deny-all config; nothing reaches the network |

| E-04 | P1 | Outbound secret scan + `INJECTION_SUSPECTED` tripwire (05 §17 #24–26): scan proposed payloads and effector requests; listing/inbound text matching injection patterns emits an `INJECTION_SUSPECTED` receipt and forces tier 0 + `needs_review` | none | READY after E-02 | 05 | Tests: a secret in a payload is refused; an injected listing yields at most a tier-0 proposal with the tripwire receipt |
| E-05 | P2 | Stuck-claim reconciliation job: executions left `executing` past a TTL are reconciled through the gateway (provider-query-before-retry semantics, dry-run) | none | READY | 05 | Test: a crashed claim is reconciled exactly once; no re-send |

### Lane F: Agent 06 (Operator UI)
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| F-01 | P1 | R10: Operator UI on `spine.pending_decisions` / `spine.decide(channel="web", new_payload=…, hold=…, auth_context={"step_up":…})` + `notify_decision`; drop the UI gateway, ticker and SQLite store | none | **DONE** @ `190bb9b` | 06 | A YES/NO/MODIFY/HOLD web flow against 01's spine on Postgres (pgserver) |
| F-02 | P1 | ADR-0010: `util.canonical_json` → reference; stand-in `row_hash` → MBOS-RH-1 | none | **DONE** @ `fc31896` | 06 | interop row 06 = 10/10 |
| F-04 | P2 | P-06-3: the UI's `SpineBackend` uses the worker's real `Components` (05 PDP) | A-03 | BLOCKED | 06 | UI decisions use the real PDP |
| F-03 | P2 | Comms dry-run spec items (1)(3)(4)(6) from 06's status: templates registry, rate/consent rules as data | none | **DONE** @ `cb787dd` | 06 | Data files + tests; no sends |

| F-05 | P1 | P-06-4: `CommsActionPlanner` implementing `mbos.interfaces.ActionPlanner` from the comms_spec template registry. The payload carries `template_id`, `template_hash` (MBOS-CJSON-1) and the rendered draft; action constraints (window, consent prerequisites) go in the payload | none | READY | 06 | Contract-valid proposals for 1 flip + 1 service fixture; 01 wires it into `Components` (A-13) |
| F-06 | P1 | P-06-5: dry-run comms `Effector` implementing `mbos.interfaces.Effector`: exactly-once per idempotency key; `effector_response.dry_run=true`; `details.kind=comms` carries consent/DNC/window/disclosure check results; `audit(receipts)` grades E1–E7. No network imports | none | READY | 06 | E1–E7 graded on a spine run; A7 still zero exceptions |

### Lane G: Agent 07 (QA)
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| G-01 | P1 | ADR-0010: `core.canonical`/`receipt_row_hash` → reference; add `vectors.json` to `mbos_qa interop`; re-run interop across all lanes and publish the matrix | none | **DONE** @ `9cbce70` (docs/qa/INTEROP_REPORT.md) | 07 | Matrix published; F-13/F-14 closed or re-opened with evidence |
| G-02 | P1 | **R11 amended: start now.** 07 writes `MBOS_QA_IMPL` = `mbos_qa.impl_spine:build` against 01's public API (`mbos.runtime`, `mbos.spine`, `mbos.ledger`, `mbos.audit`, `mbos.workflows`) on pgserver Postgres. Re-target the store to 04's schema when A-01 lands | none (A-01 later) | **CLAIMED** | 07 | A1–A10 from `qa/` run against the real spine; results reported as real, not mocked |
| G-03 | P2 | G1–G4 marketing tests against the real ActionRequest/approval path (publishing drafts as dry-run ActionRequests) | G-02 | READY after G-02 | 07 | G1–G4 green on the real spine |

## Operator infrastructure (not a business decision; outside the repo)
- **X-01 (P1, PROVENANCE):** the shared `.git/config` identity is overwritten by the last-launched agent (07 P-07-2, verified by 01). All of 01's Round Two commits are recorded as "Agent 07 Marketing". The fix is in `~/bin/mbos-agent`: enable `extensions.worktreeConfig`, then set `git config --worktree user.name/user.email`. Interim rule: per-commit `-c user.name/-c user.email` (docs/COORDINATION.md). The correction receipt is in `docs/receipts/2026-10-07-provenance-correction-commit-authorship.md`.

## Michael (business-policy only; nothing blocks the dry-run MVP)
- MICHAEL_DECISIONS #1–#5 are unchanged.
- **Optional:** an eBay developer keyset for live read-only eBay discovery (Agent 02's runbook). Not required; fixture mode runs the same code.
