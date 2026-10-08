# Agent Status

Agent: 07
Role: ROUND TWO — QA / End-to-End Integration / Manual-Assist Outputs (lane G)
Branch: research/agent-07-marketing
Worktree: /home/michaelos/business-os-worktrees/agent-07-marketing
State: IDLE
Done: G-01 @ 9cbce70
Done: G-02 @ a1700d9
Done: G-03 @ 4c2e897
Done: G-04 @ 6d43d2b — wave-two RC verdict NOT READY (F-24 blocking; F-25 needs a ruling; F-22/F-23 open)
Done: G-05 @ 3c330e8 — 148 pass / 87 fail → F-26..F-39 (3 of the highs: F-26 crash, F-31 dry-run shown as sent, F-35 text-view forgery; F-36 poison listing)
Done: G-06 @ e7434f4 — RC re-run NOT READY on ONE red case (F-40, fails safe); safety invariants HOLD; F-22/23/24/25 verified closed
Done: G-07 @ 5e66a02 — RC READY (105/0, dry-run scope, stable x2); card 232 pass / 11 residual; F-40 and F-41 closed with direct tests
Done: G-07 final re-run @ 40170f6 — card 245 pass / 2 low residuals (F-28 numeric date, F-30 ADR/contract marker); RC still READY 105/0 at mbos deec1d1
Done: G-07 final pass @ 5312f47 — card 248/0; RC READY 105/0; reference 104/0 at mbos e755b38 + 05 E-16 716098e; every card finding closed or accepted (F-39, R25)
Done: G-08 — A-15 follow-up: F-42 (orphan on crash), F-45 (concurrent double submit → 2 live requests), F-43, F-44; release gate goes red on failing test / modified installed code / live-mode policy / broken chain formula, but NOT on weakened contract (F-46), all-skipped suite (F-47), extra/json stale install (F-48); e2e executes no action (F-49). Receipt docs/receipts/2026-10-07-G-08-followup-and-release-gate.md
Claimed: (none; waiting for the next READY task)
Waiting on: Agent 01 to triage F-42…F-49 (all open, owners in the receipt). Card and RC suites have no open findings. Re-run any time: `python -m mbos_qa install-pins`, then `card` and `spine --rc`.
Current phase: Round Two — G-07 delivered; waiting on the remaining card fixes
Started: 2026-10-06 (round one) · 2026-10-07 (round two)
Last updated: 2026-10-07

## Work queue (foreman loop, docs/COORDINATION.md)
- **Done: G-01 @ 9cbce70.**
  - ADR-0010 interop matrix: `docs/qa/INTEROP_REPORT.md`. Receipt: `docs/receipts/2026-10-07-G-01-adr0010-interop.md`.
  - F-14 and F-13 are RULED. Conformance is open only for lane 03 (C-02), lane 04 (D-02) and the second `mbos.receipts` (A-01 phase 2). Every other lane and SQL twin passes `vectors.json`.
- **Done: G-02 @ a1700d9.** `qa/` A1–A10 run against Agent 01's REAL spine (`mbos` @ `c5c7c1c`, PostgreSQL 16 + DBOS): **90/90 pass**, stable across 3 runs. Report: `docs/qa/SPINE_ACCEPTANCE.md`. Receipt: `docs/receipts/2026-10-07-G-02-spine-acceptance.md`.
- **G-03 @ c713cbf** (re-pinned to `a910ad9`):
  - G1, G2 and G4 (draft frozen into the approved payload) are green on the real spine. F-18, F-19 and F-20 are verified fixed.
  - **Residual F-21:** the G4 clause "prompt version and model in provenance" is not met. It is a strict xfail, and I've proposed P-07-8.
  - G3 is not applicable. Real-spine suite: 96 passed, 0 failed (`docs/qa/SPINE_ACCEPTANCE.md`).
- **Next:** finish G-03 when P-07-8 lands or Agent 01 rules on it. Then P-07-5, after A-03.


## G-04 result @ 6d43d2b: wave-two release candidate = NOT READY
- Stack: `mbos` @ `ca6d056` with `state_backend=lane_d` and `gateway_mode=lane_e`, Agent 04 schema @ `a08dd9f`, Agent 05 gateway @ `101a7e6`. PG16 + DBOS.
- 88 passed, 9 failed, 6 strict xfail, 3 n/a. Stable across 2 clean runs. `docs/qa/RELEASE_CANDIDATE.md`; receipt `docs/receipts/2026-10-07-G-04-release-candidate.md`.
- **F-24 (blocking, 05+01):** a gateway denial leaves the request `approved`. After the freeze lifts, the stale approval EXECUTES while the item is FAILED.
- **F-25 (ruling, 05+01):** a kill mid-ACT never duplicates, but ends FAILED instead of resuming to ACTED. Is A5 'resume' or 'at-most-once, re-approve'?
- **F-22 (05):** nobody holds a `publish.listing.create` grant, so the flip/publishing path is denied. **F-23 (01):** a PDP-denied item still goes to AWAITING_APPROVAL.
- Re-run after fixes: `python -m mbos_qa spine --rc` (about 2.5 minutes). The strict xfails flip to failures when F-22/F-23 close, and the marker must then be removed.

## G-05 result @ 3c330e8: card acceptance (ADR-0011)
- 148 passed, 87 failed of 236 across pure, reference and lane D+E. `docs/qa/CARD_ACCEPTANCE.md`; receipt `docs/receipts/2026-10-07-G-05-card-acceptance.md`.
- High: F-26 (build_card crashes on malformed enrichment), F-31 (dry-run shown as CONTACT SENT), F-35 (text-view forgery/ANSI/1 MB), F-36 (a NUL listing aborts the discover batch).
- Held: no invented NEGOTIATING/QUALIFIED; trail = ledger 1:1; read-only; process-stable hash; no authority fields.
- Re-run: `python -m mbos_qa card` (about 45 s).

## G-06 result @ e7434f4: release candidate = NOT READY on one case
- 103 passed, 1 failed (F-40), 3 n/a; stable over two runs; reference config 104/104. `docs/qa/RELEASE_CANDIDATE.md`; receipt `docs/receipts/2026-10-07-G-06-release-candidate-rerun.md`.
- Pins: mbos `f8407c9`, lane D `92d52b1`, lane E `e6afc28` (all by `git archive`).
- **Closed and verified:** F-24 (A9 8/8), F-25/R22 (A5 5/5), F-22, F-23.
- **Red:** F-40 (01+05). A publishing YES without step-up is accepted, then refused by the gateway, and Michael's approval is lost. It fails safe.
- Observation F-41 (05): the proposer identity holds propose-only grants for every money-moving capability.

## G-07 result @ 5e66a02
- **Release candidate READY (dry-run scope):** 105 passed, 0 failed, identical across 2 runs; reference config 104/0; mock suite 77/0/1. `docs/qa/RELEASE_CANDIDATE.md` states the scope: no live providers, LiteLLM, real egress cut, lane C engine or UI.
- Pins (verified byte-identical by `mbos_qa.pincheck`): mbos `2d4e8dd`, lane D `c97ba6b`, lane E `87f0b53`.
- **Card:** 232 passed, 11 failed. Open: F-36 (a NUL aborts discover in normalize_step; 01+02), F-30 (3/42 phrasings, no model-specific marker; 01+03), F-28 (dates; 01), F-31 (headline lacks a dry-run marker; 01), F-27 (a malformed risk source; 01). F-39 is accepted (R25).
- Receipt: `docs/receipts/2026-10-07-G-07-final-rerun.md`.

## Proposed tasks
- **P-07-18 (01) F-36:** isolate each record in `discover` (try/except around normalize_step, convert domain errors to picklable ones), so one bad listing cannot abort the batch regardless of the normalizer.
- **P-07-16 (01 + 05) F-40:** `decide` consults the PDP's step_up requirement on the request and refuses a YES that lacks it; a guard-refused request settles failed, not `approved`.
- **P-07-17 (05) F-41:** per-lane propose grants (06: comms; 07: publishing), the spine identity limited to what its default planner emits.
- **P-07-13 (01) F-26/F-27/F-28/F-36:** harden the card builder against malformed enrichment (type-check, sanitise, validate values) and quarantine NUL/invalid-JSON listings at ingest; add the fuzz and poison-listing tests to 01's suite.
- **P-07-14 (01 card + 06) F-31/F-32/F-35:** a dry-run is not 'sent'; derive timeline stages from typed documents; escape/truncate untrusted fields in `render_text`.
- **P-07-15 (01 + 03) F-29/F-30:** `why` as sourced datums; real source requirement, a model-specific marker, a wider/normalised lint driven by data.
- **P-07-9 (05) F-24:** on a G7 (or any guard) denial, set the request `approved → cancelled_by_freeze` (or `failed`) in the same transaction as ACTION_FAILED, so a denied approval can never be replayed.
- **P-07-10 (05+01) F-22:** a propose-only grant for `publish.listing.create` (R7 pattern), or let drafting lanes propose under their own id.
- **P-07-11 (01) F-23:** on a PDP deny, archive or fail the item instead of AWAITING_APPROVAL.
- **P-07-12 (ruling, 01/05) F-25:** define A5 for lane E (resume vs at-most-once) and make the simulated provider's delivery log durable. (for Agent 01 to triage)
- **P-07-1 (01), F-16:** ship the contracts as package data, or fail clearly. A non-editable install of `mbos` fails 94 of 109 tests without `MBOS_CONTRACTS_DIR` (`docs/qa/BUILD_VERIFICATION.md`).
- **P-07-2 (launcher owner / Agent 01), F-17, provenance:** the git identity is stored in the shared `.git/config`, so the last-launched agent signs everyone's commits. 01's commits `acb6f3b`, `c6c5ad4`, `7ed5705` and `bed7609` are authored "Agent 07 Marketing". Fix: `extensions.worktreeConfig=true` plus `git config --worktree user.*` in `~/bin/mbos-agent`. I have not changed any shared config.
- **P-07-4 (01), F-18:** `spine.decide` refuses NO-without-reason through `ContractViolation` rather than `DecisionRefused`. Validate the approval before any write and raise one exception type.
- **P-07-5 (07, after A-03/E-02 and A-01 phase 2):** re-run `python -m mbos_qa spine` once lane E's real gateway, PANIC and budget, and Agent 04's store, are wired. A5/A8/A9 currently exercise 01's reference stand-ins.
- **P-07-6 (01), F-19, approval integrity:** let `ActionPlanner` return an optional `draft` (content, content_hash, template_version, prompt_hash, model_id). `_propose` copies it into the hash-frozen payload, and the Operator UI shows it. `mbos_qa.marketing_planner` already emits it. Unblocks G4.
- **P-07-7 (01), F-20:** add `attribution=` to `spine.record_outcome` (or record attribution at intake for `service_lead`). Unblocks G2.
- **P-07-8 (01), F-21:** when a proposed action carries `draft`, record a provenance row (drafting agent; `model_id`, `model_version`=template version, `prompt_hash`; `inputs_used`=content_hash) and cite it in the request's `provenance_ids`. Or rule that payload freezing satisfies G4. Note: P-07-4, P-07-6 and P-07-7 are verified fixed at a910ad9.
- **P-07-3 (01):** refresh the test-count claims in ALL_AGENTS from `docs/qa/BUILD_VERIFICATION.md`. Collected counts: 01 has 109 vs 111 claimed, 03 has 114 vs 75, 05 has 121 vs 114.

## Current objective
Independent QA/integration lane against the frozen contracts v1.0.0. DRY-RUN ONLY.

## Completed (round two)
- `qa/`: QA harness (Python 3.12, jsonschema, pytest). Read `qa/README.md` first.
- **Contract validation runner:** pinned byte-exact contracts with a sha256 manifest, a drift check against the coordinator branch, and 21 negative invariants. It also runs 5 gap probes for rules the ADRs state but the schemas do not enforce. Result: 31/31.
- **Acceptance orchestration:** `python -m mbos_qa run` runs the contract checks, the e2e run and the pytest suite, then writes `docs/qa/ACCEPTANCE_REPORT.md`.
- **A1–A10 + G suite:** 76 pass, 0 fail, 1 strict-xfail (known gap F-5).
- **E2E fixtures:**
  - One synthetic flip: a trailer listing with a planted prompt injection. Flow: YES on the seller email, then MODIFY → YES on the resale listing.
  - One synthetic service: a drywall lead with attribution. Flow: HOLD → wake → MODIFY → YES.
  - Report: `docs/qa/e2e/E2E_REPORT.md`, covering source, normalization, economics, recommendation, approval, dry-run action, receipts and provenance.
- **Dry-run manual-assist packets** (real, owned by this lane): `docs/qa/e2e/packets/`. Each packet is content-addressed, and its hash is on the `ACTION_EXECUTED` receipt.
- **Mocks** for lanes A, B, C, D and E are clearly labelled `MOCK` in code and in every report, and sit behind the `MBOS_QA_IMPL` seam.

## Cross-lane interop against the peers' real code (docs/qa/INTEROP_REPORT.md)
Peer refs checked: 01 c6c5ad4 · 02 5b62625 · 03 dcd6883 · 04 3af8e92 · 05 03db146 · 06 3e51ba4.
- PASS (FACT): the vendored contract copies in 02, 04 and 05 are byte-identical to the frozen pin. 01 and 06 read the coordinator path.
- PASS (FACT): all 13 Agent 03 scored examples (26 documents) validate against frozen Item/Provenance v1.
- PASS (FACT): every lane computes the same payload_hash for int, string, unicode and nested payloads.
- **FAIL (FACT) F-13, blocking for integration:** two lanes (01 and 04) each define `mbos.receipts`. Their row_hash formulas differ from each other and from the contract text used by 05, 06 and 07. On real PostgreSQL 16, one identical receipt produced 3 different row_hashes, so no lane can verify another lane's chain.
- **FAIL (FACT) F-14:** `{"offer": 850.0}` hashes differently in 03 (Decimal normalisation) than in 01, 02, 06 and 07. 05 refuses floats entirely.
- **FAIL (FACT) F-15:** 03 changed its schemas but kept the pinned `$id`. Nothing breaks today.

## Findings (all in docs/qa/ACCEPTANCE_REPORT.md)
- F-1: the example hashes are not reproducible, and the contract does not pin the exact bytes. (01)
- F-2: 5 schema gaps. The runtime enforces each one. (01)
- F-3: no `superseded` status for requests closed by MODIFY. (01/05)
- F-4: `INSERT OR REPLACE` bypassed the DELETE trigger in SQLite. The Postgres analogue is `TRUNCATE`. (04)
- F-5: tail truncation needs an anchor. 04's code has one; QA has not exercised it yet. (04)
- F-6: budget reservations must be durable. (05/04)
- F-7 / F-8: A2 roles, A8 against LiteLLM and A9 egress are proven on mocks only. (05/04)
- F-9..F-12: item state with multiple actions, the guard-denial receipt type, step-up fatigue, and the coordinator validator skipping `format` checks.
- F-13..F-15: see the interop section above.

## Blockers
None.

## Needs Michael decision
None new. (Round-one marketing questions remain parked until marketing go-live.)

## Needs coordinator review
- **F-13 (blocking for integration):** rule on one receipts ledger and one byte-exact row_hash formula. 01 and 04 currently both define `mbos.receipts`.
- **F-14:** rule on number canonicalisation for hashed payloads: no floats (05) or RFC 8785 JCS everywhere.
- F-1, F-2, F-3, F-9 and F-10 touch the frozen contracts. A v1.1.0 bump is proposed and is for Agent 01 to decide.

## Next action
1. Wire `MBOS_QA_IMPL` to Agent 01's spine (`mbos.runtime` / `mbos.interfaces`) and re-run A1–A10 on real Postgres and DBOS.
2. Re-run A2 (roles), A3 (anchors) and A5 against Agent 04's store, and A8/A9 against Agent 05's gateway and PANIC.
3. Re-run `python -m mbos_qa interop` once F-13 and F-14 are ruled on.
