# Round Two Integration: Coordinator Rulings and Lane Seams

**Author:** Agent 01 (coordinator, integration owner)
**Date:** 2026-10-07
**Status:** rulings R1–R11 are BINDING for wave two. **R2 and R3 are made byte-exact by ADR-0010 (ACCEPTED, F-13/F-14).** Other contract changes are only PROPOSED (ADR-0009). Work allocation: `docs/status/READY_QUEUE.md`.

**Inputs, read only via `git show` with nothing merged.** All six specialist branches have round-two code pushed.

| Lane | Branch @ commit | Package | Claimed tests |
|---|---|---|---|
| B Discovery | agent-02 @ `5b62625` | `src/mbos_discovery` | 56 |
| C Economics | agent-03 @ `dcd6883` | `economics/src/mbos_economics` | 75 |
| D State | agent-04 @ `3af8e92` | `state/mbos_state` + SQL `0001–0004` | 93 |
| E Governance | agent-05 @ `03db146` | `src/mbos_governance` + `policy/policy.v1.json` | 114 |
| F Operator UI | agent-06 @ `3e51ba4` | `operator_ui/` | 29 |
| G QA | agent-07 @ `3107173` | `qa/mbos_qa` | 76 + 31 contract checks |
| A Core (this) | agent-01 @ this commit | `src/mbos` | 111, run here |

Agent 01 ran only its own suite. The other counts are the lanes' own claims (`AGENT_STATUS.md`). They are recorded as claims, not verified.

---

## 1. Verified facts (Agent 01 checked these directly)

**FACT. No contract drift.**
- Every vendored copy of the frozen v1.0.0 schemas and examples on all six branches is byte-identical to `docs/research/contracts/` (sha256 comparison).
- The one exception is Agent 03's own source schemas, `docs/research/schemas/*`. Agent 03 extended them additively to v1.1.0 but kept the same `$id`.

**FACT. Agent 03's real output already conforms to v1.0.0.** All 13 of its `economics/examples/*.scored.json` validate against the frozen `item.schema.json` and `vendor/agent-03/scorecard.schema.json`. A re-pin is optional, not blocking.

**FACT. Agent 03's real engine runs inside the spine.**
- It is installed from `dcd6883` without merging, behind `Scorer` via `src/mbos/adapters/economics.py`.
- It scored fixture Items inside the real DBOS workflow, which routed YES to AWAITING_APPROVAL, MAYBE to RESEARCHING and PASS to ARCHIVED.
- Its deterministic `scr_`/`rec_` ids are preserved.
- Test: `tests/integration/test_lane_c_economics.py`.

**FACT. A frozen example's hash does not reproduce.** In `examples/action-request-email-held.example.json`, `payload_hash` ≠ sha256(canonical(payload)). Agent 05 reported this, and Agent 01 reproduced it. It is fixed only through ADR-0009.

## 2. Coordinator rulings (binding)

| # | Conflict | Ruling | Who acts |
|---|---|---|---|
| **R1** | Two Postgres DDLs: 01 `0001_spine.sql` vs 04 `0001–0004` | **Agent 04's schema is canonical.** 04 owns DDL, and its design is more complete: gapless chain, anchors, budget/policy/lessons, role edges. Agent 01's DDL is demoted to the *reference spine* that keeps A1–A10 runnable until the port lands. Agent 01 ports `ledger.py`/`spine.py` onto 04's SQL API (`mbos.create_item`, `transition_item`, `propose_action`, `set_action_status`, `record_approval`, …). **04 adds** `effector_calls`, `governance_flags` (or 05's panic state; see R5), `llm_spend` and `artifacts`, keeping 01's `0001_spine.sql` invariants (dry-run CHECKs, insert-only). | 04: migration `0005`. 01: state adapter |
| **R2** | Three receipt-hash formulas (01 `seq\|body\|prev`, 04 `sha256(canonical doc)`, 05 SQLite) | **One chain, one formula: 04's** `row_hash = sha256(mbos.receipt_canonical(row))`. 05's and 06's SQLite ledgers are test stand-ins only. In production, every receipt goes through 04's `append_receipt`. | 05, 06: route through the store. 01: port |
| **R3** | Canonical JSON for `payload_hash` / `inputs_hash` | **Normative:** `json.dumps(obj, sort_keys=True, separators=(",",":"), ensure_ascii=False)`, UTF-8, sha256, written `sha256:<hex>`. 01, 06 and 07 already match (`mbos.hashing.canonical_json`). 04's `mbos.payload_hash` (`jsonb::text`) **must not** be used for payload hashes; hashes come from Python, or 04 implements the same canonical form in SQL. Money values are JSON numbers, emitted by Python's deterministic repr. To be written into the contract by ADR-0009 (05 R1). | 04, 05 |
| **R4** | Who owns ACTION_EXECUTING/EXECUTED/FAILED receipts and `approved→executing→executed` | **Lane E's gateway owns the action-status edges and their receipts** (05 G1 expects `approved`). The spine owns **Item** states only. It moves the item to APPROVED→ACTING, calls `Gateway.execute`, then moves the item to ACTED or FAILED from the returned result. Agent 01 removes `executing` from `begin_act` when 05's gateway is wired. | 01, 05 |
| **R5** | Kill-switch state: 05 sealed JSON file vs 01 `governance_flags` table | **05's PANIC semantics win.** State lives in Postgres (one source of truth, backed up, receipted), not a CWD file. 05 ports `PanicStore` onto a 04 table and keeps fail-closed behaviour (missing, unreadable or bad checksum all mean frozen). `KILL_SWITCH_CHANGED` receipts go through 04. | 05, 04 |
| **R6** | PDP input | The PDP receives the **full ActionRequest** draft. Already done in the spine: `spine._insert_and_classify`. | done (01) |
| **R7** | Agent identity and grants | Agent ids equal branch names. The spine proposes as **`agent-01-coordinator`**. 05 adds a **propose-only** grant for `comms.email.send` / `comms.sms.send` to `agent-01-coordinator`. Execution stays bound to 06's effector identity. Proposal ≠ execution. | 05: `policy.v1.json` |
| **R8** | Dedup | `dedup_key` is a **blocking key**, never an identity. Identity is `(source, source_listing_id)`. Merge only when the lane-B `Deduper` says so. Done in the spine: migration `0002_dedup_blocking_key.sql`, `Deduper` protocol, `spine.ingest`. 02 supplies a `Deduper` wrapping `dedup.is_cross_source_duplicate`. | done (01). 02: adapter |
| **R9** | Action proposals | Lane C recommends, and lanes 06/07 draft. The spine turns YES into ActionRequests through `ActionPlanner` (reference: `DefaultActionPlanner`). Done. | done (01). 06: real planner/templates |
| **R10** | Operator UI duplicates the gateway, timers and ledger | 06's UI keeps its UX (cards, CSRF, loopback-only, PIN step-up, HOLD presets). It **drops** `DryRunGateway`, `tick()` and its SQLite store, and calls `spine.pending_decisions` / `spine.decide(... channel="web", new_payload=..., hold=..., auth_context={"step_up": ...})` plus `mbos.workflows.notify_decision(item_id, approval_id)`. HOLD timers belong to the DBOS workflow. Already done in the spine: `decide(new_payload=...)` for the full-payload MODIFY form, and step-up enforcement for irreversible or money-like YES (matching 04's trigger and 05's policy). | 06 |
| **R12** (re-affirmed 13:00 after 04 accommodated the old edges in parallel) | Item state-machine edges (01 allowed `NORMALIZED→SCORED`, `HELD→APPROVED` and LEARNED exits; 04 follows ADR-0004 literally) | **Lane D's edge table is canonical.** Every item passes RESEARCHING. A YES on a held request re-presents it first. LEARNED is terminal. `ACTED→AWAITING_APPROVAL` is accepted for follow-up actions (ADR-0009 item 7). The spine is aligned (migration `0004`), and a parity test runs against 04's live DB | done (01) |
| **R13** | A PASS resting only on priors (03 P-03-02) | A machine PASS archives an item only when its decision rests on evidence. **Amended 13:55 (03 P-03-04):** for flips, the revenue side AND at least one cost-side input must be evidence-backed (FACT); for services, at least one decisive input. A PASS on priors alone routes to **RESEARCHING**, so the item is not discarded on assumptions. 03 flags it in the scorecard (`pass_on_priors`); the spine routes it (A-12) | 03 (C-05), 01 (A-12) |
| **R14** | Where approvals can be recorded (04's D-06 flag) | **Approvals never come from an LLM-reachable tool.** The State MCP `agent` profile has no approval, execute, spend or PANIC tools. Approvals come only from human channels: `spine.decide` (Operator UI / CLI) or 04's non-LLM `operator` profile (`mbos_operator_ui` login). Model proposes; human approves | done (04) |
| **R15–R19** (ADR-0011) | Deal Sniffer opportunity card | Card = derived view (not a source of truth); UNKNOWN never guessed; recommendation vocabulary CONTACT/OFFER/BUY/COUNTER/HOLD/PASS derived from verdict + live ActionRequest capability; status timeline only from real events; full activity trail; elementary mechanic advice rejected; transport is an economic variable (operator profile as data); enrichment via `record_enrichment` | 01 done; 02/03/05/06/07 tasks queued |
| **R20** | A freeze-refused, already-approved request (06 P-06-11) | Becomes `cancelled_by_freeze`, never left `approved`: an approval must not be silently reusable after an unrelated PANIC release (the payload or conditions may be stale). Michael re-approves after release | 05 (E-12) |
| **R11** | Two A1–A10 suites | **Both stay.** `tests/acceptance` (01) runs the **real** spine and is the release gate. `qa/` (07) is the cross-lane spec suite. 07 targets real components through `MBOS_QA_IMPL`. Agent 01 will ship `mbos.qa_adapter:build` **after R1**, because the adapter must wrap the converged store, not the reference DDL. G1–G4 stay 07's. | 01 then 07 |

## 3. Seams by lane: what exists, what is next

**B. Discovery (02)**
- Gap: `SourceAdapter` returns `FetchResult` (records, error, requests_made), not a list. `source_listing_id` and `url` only appear after `normalize`.
- Next adapter (01+02):
  - `fetch()` calls 02's `fetch(profile)` then `normalize()` per record, and emits `RawListing`.
  - `FetchResult.error` and `freeze_requests` go to a side channel that becomes an L2 capability freeze (R5).
  - `raw_ref`: the spine hashes `canonical(payload)`, while 02 hashes the original `raw_bytes`. **Ruling:** `raw_ref` is the hash of the stored raw bytes. The spine adopts 02's `raw_bytes` when present (to do in the B adapter).
- Live eBay stays disabled. It needs credentials, and Michael has not been asked; nothing is needed for the dry-run MVP.

**C. Economics (03)**
- Wired (FACT).
- Open: 02's Items carry no `economics`. The **RESEARCH/estimate step** that fills `Item.economics` from comps and listing text is the missing producer. Until it exists, real discovered Items park in RESEARCHING, which is correct and safe. Owner: 03 (estimates) with 02 (comps data).

**D. State (04)**
- See R1/R2/R3. Agent 01 builds the state adapter against `StateStore`.
- 04 must answer: the DBOS login role (`mbos_dbos`), its permissions, and whether DBOS datasource checkpoints may live in the app DB schema `dbos`.

**E. Governance (05)**
- Adapter plan:
  - `Gateway.execute(engine, areq_id, approval_id)` → `ActionGateway.execute(areq_id)`, after asserting that the latest approval equals `approval_id`. Map `Result` to `GuardResult` with `checks={G#: not codes}`, `frozen = G7 failed or status == cancelled_by_freeze`, and `reason` as the joined reasons.
  - `KillSwitch.is_clear` → `PanicState.blocks`.
  - `PolicyDecisionPoint.decide` → `policy.decide(ar, policy)`.
- Blocked on R4/R5 store convergence.

**F. Operator UI (06)**
- See R10. Canonical hashing already matches (`util.py:30`).

**G. QA (07)**
- See R11. 07's packets in `docs/qa/e2e/packets/` are labelled SIMULATED. They must never be presented as Michael's approvals.

## 4. Contract change requests, consolidated (ADR-0009, PROPOSED, NOT applied)

Requested by 02, 03, 04, 05, 06 and 07. Frozen v1.0.0 stays in force until ADR-0009 is accepted after cross-lane review.

1. Normative canonical-JSON rule (R3). Regenerate the `action-request-email-held` example hash (05 R1).
2. Receipt types:
   - `ITEM_UPDATED`: non-state Item changes such as dedup merges, today recorded as ITEM_STATE_CHANGED with before == after (02, 06).
   - `ACTION_EXPIRED` (04, 06).
   - `GUARD_REFUSED` (05). Today a refusal is ACTION_FAILED with `effect=none`.
   - `ACTION_STATUS_CHANGED` (05).
   - `SOURCE_FROZEN` (02).
3. ActionRequest status `superseded` for MODIFY (06, 07). Today the old request is `rejected` with an intent naming its successor.
4. Expiry receipts without `approval_id` (04).
5. ID prefixes `lsn_`, `pol_`, `bud_`, `obx_`, `pdp_` (04, 05).
6. `sources[].raw_ref` required (02).
7. Re-vendor Agent 03 v1.1.0 schemas with **versioned `$id`s** (03 kept the old `$id`, which must change on re-vendor).
   - Widen the `inputs_hash` scope to 03's `mbos.economics.inputs/v1` spec (ADR-03-002).
   - Annotate the trailer example as illustrative, because 03 scores it PASS (C23).
8. Item state with multiple actions per item (07 F-9).
9. Add a format checker to `validate_contracts.py` (07 F-12).

## 5. Next integration dependency (critical path)

1. **04: migration `0005`** with the R1 tables, plus answers on the DBOS role and checkpoint schema.
2. **01: port the spine onto 04's `StateStore`** (R1/R2). A1–A10 must pass unchanged on 04's schema.
3. **05: Postgres-backed PanicStore and ActionGateway store** (R4/R5). 01 wires the 05 adapter, and A5/A9 must pass with the real gateway.
4. **06: Operator UI on `spine.decide`** (R10).
5. **02: B adapter + Deduper** (R8). **03 + 02: RESEARCH/estimate producer**.
6. **01: `mbos.qa_adapter:build`** (R11). Then 07 runs `qa/` against the real system.
