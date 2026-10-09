# Agent Status

Agent: 06
Role: Communications + Operator UI / Approval UX (build lane F)
Branch: research/agent-06-communications
Worktree: /home/michaelos/business-os-worktrees/agent-06-communications
State: CLOSED
Claimed: none
Done: F-39 @ e97e057 · F-01 @ 190bb9b (+ notify_decision follow-through @ e2e42f8) · F-02 @ fc31896 · F-03 @ cb787dd · F-05 @ acb7c52 · F-06 @ 5abf51e · F-07 @ 36ce9a4 · F-08 @ 9d75e44 · F-09 @ 317a2db · F-10 @ f955219 · F-12 @ 0e5a3fe · F-04 @ 46c961c · F-13 @ 2415936 · F-14 @ c68a33c · F-13 hardening @ 6e47646 · F-15 @ 94130a4 · F-11 @ 20d88ee · F-17 @ 47c0621 · F-16 @ 9c2012d · F-18 @ d56f8d2 · F-19 @ f038a80 · F-21 @ da87d26 · F-20 @ f499a99 · P-06-12 @ 27d2d0f · P-06-17 @ 0fdf1dc · P-06-18 (notes + refusals proven; outcome REFUSED by DB, pinned) @ 8572f10 · P-06-20 @ 2c4b23e · F-22 @ 82d83e3 · F-23 @ 76b555a · F-24 @ 944093e · F-25 @ fdacf36 · F-26 @ 23af990 · F-27 @ 7756448 · F-28 @ 4e5681e · F-29 @ c638453 · F-30 @ bc050cf · F-31 (partial: F-107/108/109; F-106 BLOCKED) @ cd174fa · F-34 @ f433dd1 · F-32 @ 317e650 · F-33 @ 743250a · F-36 @ 28f18bf · F-35 @ f430b7a · F-37 @ 17031d4 · F-38 @ fff7c4c
Blocked: F-31 (F-106 form only) on a lane A/C task: nothing feeds a stored human scope override into the engine bundle (see receipt); B-22 also still READY
Started: 2026-10-06 (Round One) · 2026-10-07 (Round Two)
Last updated: 2026-10-09 (F-39 CLOSED: reference 270 passed / 0 failed; lane D+E 104 passed / 2 failed, the same pre-existing F-32 stored-input tests)

## Current objective
CLOSED (ADR-0014 / Aria 1945). Everything pushed; the lane is handed to a fresh bounded worker via `docs/handoff/LANE_06.md`. Nothing is half-applied.

## Done
- **F-39 @ e97e057:** deal card as BUY/WATCH/PASS decision on C-33 (`operator_ui/resale_view.py`), control strip + Morning Money Hunt on Today, `/resale` workflow intake→sold with receipts; simulated never earned. Receipt: `docs/receipts/2026-10-09-f39-deal-card-resale.md`. Note: a single `pytest tests` process stalled order-dependently here (each test passes alone); numbers are from 3 file groups.
- **F-38 @ fff7c4c:** glanceable Today: DONE/WORKING/BLOCKED/OPPORTUNITIES/NEXT cards (`operator_ui/glance_view.py`), receipt-backed DONE, evidence labels, existing Approve/Hold/Pass/More details controls. Receipt: `docs/receipts/2026-10-09-f38-glanceable-today.md`.
- **F-37 @ 17031d4:** F-126(b) wake via `workflows.ping`; F-128..F-135 UI fixes. Receipt: `docs/receipts/2026-10-09-f37-g23-ui-fixes.md`.
- **F-35 @ f430b7a:** `/assets` figures form: ranges (as-is value, rehab cash, hours, resale, days, keep value, tailgate months) as typed INFER records into C-30 `compare_paths`; the card recommends a path with the others shown; clearing both boxes returns a figure to UNKNOWN. Reference suite green; lane D has 1 failure, `tests/lane_d/test_wanted_f25.py::test_double_submit_loser_sees_already_recorded` (capital race), which also fails with my change reverted. Receipt: `docs/receipts/2026-10-08-f35-assets-figures-form.md`.
- **F-36 @ 28f18bf:** G-22 F-121..F-125: next move/`/mission` from live item states, labelled figures, Wanted "no source is hunting", parts-comp explanation. 245 + 106 tests. Receipt: `docs/receipts/2026-10-08-f36-reaudit-fixes.md`.
- **F-33 @ 743250a:** "I bought it" form (amount, note, PIN) on an approved/acted flip -> D-31 `mbos.record_acquisition` (owner channel; no 01 wrapper exists yet, so `SpineBackend.record_acquisition` mirrors `record_human_input`: REC for 01). Outcome form shows a clear message on a second close; card shows the closed state; `/mission` lists open flips with deployed capital. Over HTTP as `mbos_operator_ui`: bought $120 -> deployed +120, available -120 -> sold $200 -> principal back, +80 earned -> duplicate close refused. 240 + 106 tests. Receipt: `docs/receipts/2026-10-08-f33-i-bought-it.md`.
- **F-32 @ 317e650:** "Set my quote" (service leads) and "Tell me about the job" (while the engine waits on `scope_override_required`) on the card, via `spine_d.record_human_input` (A-43/D-30); CSRF+PIN, server-set author, strict finite validation, after-save text says the worker re-checks (verdict not yet changed). Over HTTP on real lane D as `mbos_operator_ui`: drywall lead MAYBE at $500 -> YES at $700 (real engine on the stored Item); unknown-category item becomes estimable after the scope; `mbos_dbos` refused. 240 + 103 tests. Pins now mbos `f34b262`. Receipt: `docs/receipts/2026-10-08-f32-set-my-quote-tell-me-about-the-job.md`. Closes the F-106 half of F-31.
- **F-34 @ f433dd1:** `/assets` My assets (owner channel, CSRF+PIN): BBQ trailer added from the owned-trailer spec, photo references, inspection checklist with basis (verified refused), C-30 five-path card with UNKNOWNs named. 232 + 100 tests. Receipt: `docs/receipts/2026-10-08-f34-my-assets.md`. Pins now mbos `24e630f`, economics `3dc8a49`.
- **F-31 (partial) @ cd174fa:** F-108 comp doc carries `for_item_id`; F-107 engine's true gap text per code; F-109 banner says the worker will re-check. F-106 form NOT built: no code path consumes a stored human scope override (proposed task for lane A/C). 228 + 100 tests. Receipt: `docs/receipts/2026-10-08-f31-partial-comp-pairing-gap-text.md`.
- **F-29 @ c638453:** UI half of the operator audit: F-88 owner DSN + red notice, F-89 FROZEN help, F-90 Confirm forms (`record_attestation`), F-92 truthful comp message, F-94 mission titles/waiting-on/HOLD, F-95 one figure per concept, F-97 edit campaign, F-98 Today header, F-100 hide unconfigured tabs. 224 + 100 tests (`tools/run_tests.sh` exit 0 · exit 0). Receipt: `docs/receipts/2026-10-08-f29-ui-audit-fixes.md`. Pins now mbos `cb55fe8`, economics 0.14.0; vendored mission/inventory schemas are stale (not edited).
- **F-22 @ 82d83e3:** `/numbers` My numbers page: weekly target, hours, cash situation (blank = UNKNOWN) via `mbos.set_mission`; five ledger fields; Fund/Withdraw via `capital_fund/withdraw`; CSRF+PIN, server-set human actor, one receipt each; proven as the real `mbos_operator_ui` role, agent roles refused. 167 + 68 tests. Receipt: `docs/receipts/2026-10-08-f22-my-numbers.md`.
- **P-06-17 @ 0fdf1dc:** `/mission` on lane D now calls 03's `mission_feed.plan_from_db` (live Items + `capital_position_document()`), validated with `plan_errors`; the file stays as fallback and the page names its source. 167 + 43 tests. FINDING: Items with scorecards lacking `branches` crash the producer (KeyError) -> fallback; proposed P-06-18 for lane 03. Receipt: `docs/receipts/2026-10-07-p0617-mission-live-plan.md`.
- **F-20 @ `f499a99`:** `/intake` conversational-intake draft flow on `mbos.intake`; asks only missing questions (safety first), answers carry basis, nothing verified, never published. 166 + 31 tests. Receipt: `docs/receipts/2026-10-07-f20-intake-front-door.md`.
- **F-19 @ `f038a80`:** `/preview` renders four audience views of an inventory object (classified, flipper, mechanic, parts buyer) with deterministic templates (no LLM). Each is a lint-gated DRY-RUN draft: defects are verbatim, terms copied, bases and provenance carried, unknowns said. A view that fails `mbos.merchandising.lint` is refused, never softened, and "check my wording" refuses a dropped disclosure, overclaims and false verification. 154 + 31 tests. Receipt: `docs/receipts/2026-10-07-f19-audience-previews.md`.
- **F-18 @ d56f8d2:** the Weekly Mission page (`/mission`) from a validated mission plan file. A plan failing `mbos.mission.plan_errors` is not rendered; a null target or hours shows UNKNOWN and the gap stays UNKNOWN; DO_NOT_SPEND is a red banner first; the five-field capital position; every leg links to its card (unverified ones flagged); plan order, no profit sorting. Read-only. 145 + 31 tests. Receipt: `docs/receipts/2026-10-07-f18-weekly-mission.md`.
- **F-16 @ 9c2012d:** Edit (a new version, `supersedes`) and Retract (a reason is required) on `/notes`, with CSRF, the PIN and a server-set author; every refusal reason shown; only the head can be changed. After a retraction the next card no longer shows the risk, and the history keeps it. 133 + 31 tests. Receipt: `docs/receipts/2026-10-07-f16-edit-retract-notes.md`.
- **F-17 @ 47c0621:** the Capital section on the card: class, cash multiple and velocity prominently with the downside beside them; parts-out floor, repair uncertainty, liquidity, skill fit and personal-use value; UNKNOWN visible, with a banner for the cash situation. Tested on Michael's three examples; a static test forbids sorting or filtering by profit. 133 + 27 tests. Receipt: `docs/receipts/2026-10-07-f17-capital-section.md`.
- **F-11 @ 20d88ee:** Follow-up questions / Offer / Quote buttons on an ACTED card, each its own step-up request via `workflows.propose_followup` (drafts from the comms planner; offers never above the ask). Verified on lane D + E, including a separate UI process. 124 + 27 tests. Receipt: `docs/receipts/2026-10-07-f11-followup-buttons.md`.
- **F-15 @ 94130a4:** every `CommsActionPlanner` action carries `lane="agent-06-communications"`. On lane D + E the ledger's `proposed_by` equals it, `lane` is absent from the frozen payload, and a capability no lane holds creates no request (the card says "policy blocked").
  - **Bug fixed:** 05's PDP denies any `comms.*` payload with a key named `binding` at any depth (even `false`). My draft flag is now `is_binding`, pinned against the real policy file.
  - 124 + 21 tests. Receipt: `docs/receipts/2026-10-07-f15-lane-tag.md`.
- **F-13 hardening @ `6e47646`:** re-vendored card schema (flags, dry_run, why_provenance); `item.flags` warning, DRY-RUN tag, provenance links, `clean_text` on displayed text.
- **F-14 @ c68a33c:** "Add what you know about this model".
  - Server-set author, PIN-gated, every refusal reason shown, append-only and receipted; `/notes` lists them.
  - End to end on the real lane-C engine, a note shows on the next card of that model as Michael's RECOMMENDATION with his provenance.
  - 119 + 18 tests pass. Receipt: `docs/receipts/2026-10-07-f14-operator-notes.md`.
  - The pinned freeze test flipped to `cancelled_by_freeze` (R20 / E-12).
- **F-13 @ 2415936:** the ADR-0011 opportunity card is the primary view at `/item/<id>`, built only from `mbos.card` (Agent 01's API).
  - All sections, UNKNOWN shown as UNKNOWN, escaped text, validate_card banner, every receipt in the trail.
  - Decision controls beneath the RECOMMENDATION block (human channel, R14) return to the card.
  - Works with zero enrichment, on both backends. 118 + 11 tests pass.
  - Receipt: `docs/receipts/2026-10-07-f13-opportunity-card.md`.
- **F-04 @ 46c961c:** the UI runs on lane D with lane E's real Components (`lane_e_components`).
  - Reads come from lane D's document views; writes only through `spine_d`.
  - Reference suite 108 passed; lane D + lane E suite 9 passed (`tools/run_tests.sh`).
  - YES runs through Agent 05's gateway with exactly one EXECUTING and one EXECUTED receipt; the real PDP classifies MODIFY successors; a freeze yields 0 effector calls.
  - Receipt: `docs/receipts/2026-10-07-f04-ui-on-lane-d-lane-e.md`.
- **F-12 @ `0e5a3fe`:** local daily summary (`python -m operator_ui summary` writes `.md`/`.html`, plus the `/summary` page), never sent.
  - Contents: digest top-N, HOLD backlog (overdue first), yesterday's outcomes (America/Chicago) with net $, and source health.
  - Deterministic from `as_of`: byte-identical output across runs and shuffled input, with a `summary_hash`.
  - Untrusted text is escaped in markdown and HTML. Files are written atomically and locally. No network imports.
  - 108 tests pass on spine `a910ad9`, which also adopts `record_outcome(channel="web")`.
  - Receipt: `docs/receipts/2026-10-07-f12-daily-summary.md`.
- **F-10 @ `f955219`:** `/digest` renders lane C's C-08 ranking **unchanged**.
  - Escaped titles linked to open cards; action and reason; deadline window; value $/h; refs with `/provenance/<id>` links.
  - Non-engine scorecards are listed as "Not ranked". A missing engine or an engine failure is reported.
  - Tests run with the real lane-C engine; the page order equals a direct `build_digest` call (same digest hash). 101 tests pass.
  - Receipt: `docs/receipts/2026-10-07-f10-morning-digest.md`.
- **Lane D compat @ `0299a31`:** `comms_spec.ledger.ensure_schema()` skips when `mbos_comms.contacts` exists. Agent 04 adopted the F-07 schema as migration 0011 (D-10), and it is owner-managed there.
- **F-09 @ `317a2db`:** Operator UI pages.
  - Outcome entry on settled cards via `spine.record_outcome` (receipted, with LEARN predicted-vs-actual pairs) and `/outcomes`.
  - `/holds` HOLD backlog with an overdue flag.
  - `/sources` read-only lane B source health, worst first, with staleness and escaping.
  - Human channel only (R14). 96 tests pass on spine `c23bee8`.
  - Receipt: `docs/receipts/2026-10-07-f09-operator-ui-pages.md`.
- Re-pin to `c23bee8` (`19b0982`): the seq-gap finding is fixed by A-16 and is now a regression test where both verifiers agree. P-06-9 is asserted (ACTION_FAILED intents name the block reason).
- **F-08 @ `9d75e44`:** `plan_followup` / `plan_offer` / `plan_quote` each draft their own ActionRequest.
  - Binding drafts use `offer.<channel>.send`, so the spine classifies them as category `offer` (tier 0, irreversible, step-up). An offer is never drafted above the ask.
  - The effector blocks binding drafts under `comms.*`.
  - On the spine, YES without step-up is refused, and there are 0 effector calls (nothing auto-sends).
  - 85 tests pass. Receipt: `docs/receipts/2026-10-07-f08-followup-and-binding-drafts.md`.
- **F-07 @ `36ce9a4`:** consent ledger + DNC scrub store.
  - Schema `mbos_comms` is insert-only and PROPOSED for lane D. Raw contact values live only in `contacts`.
  - Each consent, revocation or STOP, and DNC scrub is written in one transaction with provenance and a chained receipt.
  - `ConsentLedger` lookups fail closed.
  - **On the real spine, E2 is graded PASS and E4 PASS**; without consent the send is blocked → ACTION_FAILED.
  - A-13 is verified: the shim is removed. 72 tests pass.
  - Receipt: `docs/receipts/2026-10-07-f07-consent-ledger-dnc-store.md`.
- **F-06 @ `5abf51e`:** `comms_spec/effector.py` `CommsDryRunEffector`.
  - Exactly once (it replays before evaluating) and sends only the frozen `payload.comms` draft.
  - Fail-closed checks: template integrity, E1 disclosure, E3 window, rate limits and DNC. Consent is recorded as `not_evaluated`.
  - Blocked attempts are recorded with `status=blocked`.
  - On a spine run, `audit()` grades E1/E3/E6/E7 PASS, E2 DRY_RUN_EXEMPT and E5 not testable. A7 has 0 exceptions.
  - Receipt: `docs/receipts/2026-10-07-f06-comms-dry-run-effector.md`.
- **F-05 @ `acb7c52`:** `comms_spec/planner.py` `CommsActionPlanner`. It drafts first contact only, carries a `comms` block (template_id, MBOS-CJSON-1 template_hash, rendered draft, constraints) and sanitizes listing text. Contract-valid flip and service proposals. **A-13 must merge `payload_extension(pa)` into the payload.** Receipt: `docs/receipts/2026-10-07-f05-comms-action-planner.md`.
- **F-01 follow-through @ `e2e42f8`:** the UI now calls the spine's `mbos.workflows.notify_decision` (A-07, which closes P-06-1). The spine is re-pinned to `bf215b2`, and a new test covers R12: a YES on a HELD item re-presents it, then executes once. 42 tests pass.
- **F-03 @ `cb787dd`:** comms dry-run spec as data in `comms_spec/`:
  - a template registry with ADR-0010 content hashes and binding flags; every template is a draft pending Michael;
  - Q&A for all 10 flip and all 9 service categories;
  - send-window, rate, consent, DNC and opt-out policy;
  - E1–E7 thresholds;
  - pure checks and a receipt auditor.

  There is no send path, and a test enforces that. Spec: `docs/research/agent-06-comms-spec.md`. Receipt: `docs/receipts/2026-10-07-f03-comms-spec-data.md`.
- **F-02 @ `fc31896`** (ADR-0010):
  - `operator_ui/mbos_canonical.py` is a byte-identical copy of the reference.
  - The card verifies `payload_hash` independently, and offers YES only on a match.
  - The ledger re-verifies the chain with MBOS-RH-1 in Python.
  - **Interop row 06 = 10/10 CONFORMS** (with row 06 repointed; see coordinator review).
  - The spine is re-pinned to `99e9ec0`. 15 tests pass. Receipt: `docs/receipts/2026-10-07-f02-adr0010-conformance.md`.
- **F-01 @ `190bb9b`** (ruling R10): the Operator UI runs on the spine.
  - Every YES/NO/MODIFY/HOLD is `mbos.spine.decide(channel="web")` in one transaction, plus a DBOS wake.
  - HOLD timers live in the item workflow. "Wake now" sends `michael_ping`.
  - The UI's own gateway, `tick()`, SQLite ledger, mock effector and seed data are removed. A test guards against them coming back.
  - Kept: cards, CSRF, loopback-only, Host check, PIN step-up, HOLD presets.
  - **11 tests pass against the real spine** (DBOS + pgserver Postgres 16; `mbos` pinned at `bed7609`, installed, not merged).
  - Receipt: `docs/receipts/2026-10-07-f01-operator-ui-on-spine.md`. Spec: `docs/research/agent-06-operator-ui.md`.
- Wave one (`3e51ba4`): first UI with a SQLite stand-in, 29 tests. Superseded by F-01.
- Round One: comms research, ADR-001/002, receipts 01–04.

## Findings (F-01)
- FACT: `notify_decision`, named in R10, does not exist in the spine at `bed7609`. The UI uses the same wake as `mbos decide` (`DBOSClient.send(item:<id>, …, topic="decision")`).
- FACT: the item workflow acts on `hold_until`, `escalate_after`, `renotify_after` and `michael_ping`, but **not** on `new_info`, `price_change` or `auction_ending` in `wake_on`.
- FACT: the spine always archives after NO, so the UI's "archive?" checkbox was removed.
- INFERENCE: `SpineBackend.components` must equal the worker's `Components`, because `spine.decide` classifies MODIFY successors with the PDP. This matters once A-03 wires 05's PDP.

## Blockers
None.

## Needs Michael decision
None. Live comms stay disabled (MICHAEL_DECISIONS #4).

## Needs coordinator review
- Resolved in `bf215b2`: interop row 06 now points at the vendored reference. P-06-1 became A-07 (DONE), P-06-2 became A-08 (READY, lane A), and P-06-3 became F-04 (BLOCKED on A-03).
- **A-13 requests (from F-05/F-06):**
  1. `_propose` merges `payload_extension(pa)` into the payload before hashing.
  2. `finish_act` maps `effector_response.status=="blocked"` to ACTION_FAILED.
  3. Optionally, merge `effector_response.comms` into `details`. F-06's acceptance text says the checks belong in `details`; the gateway at `0d107df` builds `details` itself, so they ride in `effector_response.comms` today, and `audit()` reads either location.
- RESOLVED in `c23bee8` (A-16): **FINDING (spine @ `aa88e7a`, lane A):** receipt `seq` comes from `nextval()` in `mbos.receipts_chain()`. A rolled-back receipt transaction (including A1 fault injection) therefore leaves a seq gap. `mbos.verify_chain()` checks links only and stays ok; the ADR-0010 reference `verify_chain` reports `gap before seq N`. Pinned by `tests/test_operator_ui.py::test_finding_spine_seq_gap_after_rollback_is_flagged_only_by_the_reference`. R1 (lane D's gapless chain) should close it. Until then the two verifiers disagree.
- **F-07 DDL:** ADOPTED by lane D as migration 0011 (D-10, agent-04 @ `6533334`), with identical names. On lane D, only the gateway role may record consent GRANTED or DNC CLEAR, and only it can read `contacts.value`. When A-01 phase 2 lands, the consent-recording path must run as the gateway role (`mbos_dbos`).
- **Lane C adapter note:** at `a81a989`, `mbos_economics` ships its config inside the package, so `EconomicsEngineScorer()` needs no `config_dir`. The adapter docstring is outdated.
- **ADR-0009 request:** add receipt types CONSENT_RECORDED / CONSENT_REVOKED / DNC_SCRUB_RECORDED. Under v1.0.0 these events use GRANT_CREATED/GRANT_REVOKED with `entity_type` `consent` or `dnc_scrub`.
- The comms policy values in `comms_spec/data/comms_policy.v1.json` are PROPOSED (conservative). Loosening any of them is a version bump.

## Proposed tasks
- **P-06-19 (lane D):** grant the human outcome path to `approver` (`mbos.record_outcome` is `agent_write` only), so `MBOS_APPROVER_DATABASE_URL` can serve outcome entry. Then flip `test_outcome_entry_as_the_ui_role_is_refused_by_lane_d_FINDING`.
- **P-06-18 (lane 03):** `mission_feed.plan_from_documents` / `plan_week` must skip and list (in `unknowns`) live Items whose scorecard lacks decision `branches`, not raise KeyError.
- **F-20 (P2, already READY in the queue; not started):** a UI/CLI conversational-intake draft flow on `mbos.intake` (A-27). Acceptance: "sell this mower, smokes, at least $400" yields a draft plus the ordered missing questions (safety first); every answer carries a basis; nothing is marked `verified`; it never publishes; hostile text escaped; tests on the reference and lane D suites.
- **P-06-17 (lane A/C):** nothing produces a mission plan yet (a planner that builds legs from live cards plus a mission and capital-ledger store). The F-18 page reads a plan file (`MBOS_MISSION_PLAN_FILE`) until a producer or spine reader exists.
- P-06-15 RESOLVED by Agent 01 (`build/` untracked; release gate compares installed lane packages byte for byte). Original note:  the coordinator repo commits `build/` (setuptools output) and `setup.py`. `git archive` ships a stale `build/lib`, and a non-editable install from that tree silently installs the old code (mine lacked `clean_text` until I removed `build/`). Remove `build/` from git and add it to `.gitignore`.
- **P-06-16 (lane E):** the PDP's `binding_payload_keys` check is key-name based at any depth, so an innocent flag named `binding` blocks a first contact. Consider checking only top-level payload keys, or documenting the reserved names for drafting lanes. Mine are renamed.
- **P-06-14 (lane F, now unblocked):** `mbos.spine_d.retract_operator_note(conn, note_id, entered_by, entered_at, reason)` exists (Agent 01, deec1d1 or earlier). Proposed UI task: "Retract" and "Edit" (a new note with `supersedes`) on `/notes`, with the server-set author, the PIN, and the refusal reasons shown. Not started: it is not in the queue yet, and COORDINATION says not to start unqueued work.
- **P-06-13 (lane A):** `mbos.card.load_profile()` defaults to a repo-relative path, and `card.schema.json` is not found by a non-editable install without `MBOS_CONTRACTS_DIR` (same class as A-10). The UI works around it with `MBOS_OPERATOR_PROFILE` and `MBOS_CONTRACTS_DIR`.
- R20: P-06-11 is resolved by 05's E-12 (`cancelled_by_freeze`); my pinned test must flip when it lands.
- **P-06-11 (lane A/E):** after a global freeze, a YES leaves the ActionRequest `approved` (ACTION_FAILED, item FAILED) on lane D + lane E, whereas the reference gateway used `cancelled_by_freeze`. Is that intended? Pinned as observed behaviour.
- **P-06-12 (lane D/F):** run the UI with a least-privilege approver DSN (R14) and add a test that exercises lane D's role grants (the pgserver user is a superuser).
- P-06-4 became F-05 (DONE) and P-06-5 became F-06 (DONE).
- P-06-6 became F-07 (DONE).
- P-06-7 became F-08 (DONE).
- **P-06-8 (lane A, then F):** a public `spine.propose_followup(conn, item_id, proposed_action)` plus an approval-gate workflow for follow-up requests on an existing item (the R12 edge ACTED → AWAITING_APPROVAL exists, but there is no API). F-08's tests use the internal `_propose`. Lane F would then add "Draft follow-up / offer / quote" on the UI card.
- P-06-10 is DONE in `a910ad9`, and the UI now records `channel="web"` (`mbos.web.outcome`, asserted in tests).
- P-06-9 is DONE in `c23bee8`. Original note: `finish_act` reads `response.get("blocked")` for the reason text, but the F-06 effector reports `comms.blocked_reasons`. The reason falls back to "see details", so a one-line read of `response["comms"]["blocked_reasons"]` would make ACTION_FAILED intents self-explanatory.

## Files (Round Two, current)
- `operator_ui/` (`backend`, `ux`, `views`, `server`, `sources`, `digest`, `summary`, `__main__`, `mbos_canonical`), `comms_spec/` (+ `planner.py`, `effector.py`, `data/*.v1.json`), `tests/` (conftest, test_operator_ui, test_comms_spec, fixtures/illustrative.json)
- `docs/research/agent-06-operator-ui.md`, `docs/decisions/ADR-06-003-operator-ui-stdlib.md`, `docs/receipts/2026-10-07-*.md`
- `docs/research/contracts/` (byte-identical frozen v1.0.0)
