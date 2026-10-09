# Agent Status

Agent: 03
Role: Economics / Scoring (Round-Two build lane C)
Branch: research/agent-03-economics
Worktree: /home/michaelos/business-os-worktrees/agent-03-economics
State: CLOSED
Current phase: CLOSED (closeout per ADR-0014). No claimed task.
Started: 2026-10-06
Last updated: 2026-10-08 (lane CLOSED; C-21 done; handoff docs/handoff/LANE_03.md)

## Claimed work (wave two). Foreman loop: `docs/COORDINATION.md` @ agent-01 `99e9ec0`
Claimed: none (closed)
Done: C-25 @ f7d5620; C-01 @ 42fed5e; C-02 @ 247c036; C-03 @ 22b49e6; C-04 @ 882c726; C-05 @ 6e938d2; C-06 @ 9e36ec9; C-07 @ 0c3cf4a; C-08 @ a81a989; C-09 @ 286e0f3; C-10 @ e1869f2; C-11 @ c648ca3; C-12 @ d5daf42; C-13 @ 0d417fb; C-14 @ ec97bf7; C-15 @ 2575ed3; C-16 @ c88cd5a; C-17 @ 3569efb; C-18 @ d9bceea; X-03 @ 4a93582 (already satisfied; verified 2026-10-08); C-19 @ 4f49c8b; C-20 @ 3c3201c; C-21 @ 51fc248; C-23 @ 3eb358f; C-22 @ 6b90685; P-03-14 @ 9d20b1f; P-03-13 @ bb28734; P-03-15 @ 790df23
Queue: C-22 (Valuator) DONE; P-03-10 = C-22.

- **C-01**, the RESEARCH/estimate producer, fills `Item.economics` from normalized fields, comps evidence and category priors, with provenance per estimate. It is deterministic and does no LLM arithmetic.
  - Claimed at `b923852`; confirmed CLAIMED in READY_QUEUE @ `99e9ec0`.
  - Acceptance: an Item from 02's fixtures gets valid economics and scores past MAYBE-for-missing-inputs.
- History: at `b923852` the queue files did not exist yet. The claim was taken from ROUND_TWO_INTEGRATION §3C/§5.5 and has since been ratified by the queue.
- **R1–R11 acknowledged.** No objection from lane C. ADR-03-002 = ACCEPTED-WITH-CHANGES (INDEX @ `99e9ec0`).

### C-01 result (DONE @ `42fed5e`; receipt `docs/receipts/2026-10-07-c01-estimate-producer.md`)
- `estimate_item(item, bundle, as_of)` / `apply_estimate` fill `Item.economics` from structured fields, a provenance-carrying research bundle and versioned priors (`economics/config/estimation-priors.json` 2026.10.0).
- **Acceptance met on Agent 02's real pipeline output** (`7b4d9a8`):
  - the Conway trailer plus sold comps scores MAYBE; with evidence it scores YES (walk-away $1,234)
  - all 4 service leads get real verdicts
  - no-comps flips stay `insufficient`; the resale price is never guessed
- 94 tests pass on py3.10 and py3.12.
- **For Agent 01 (A-05):** call `estimate_item` in RESEARCHING, `apply_estimate`, then `score_item`. Persist `provenance` and `receipt_draft`. Leave the item in RESEARCHING when the status is `insufficient`, and surface `gaps` as research asks.

### C-02 result (DONE @ `247c036`; receipt `docs/receipts/2026-10-07-c02-adr0010.md`)
- `canonical.py` now begins with the ADR-0010 reference `mbos_canonical.py`, byte-identical, with lane helpers appended. The engine is at 0.2.0.
- **Interop row 03 = 10/10 CONFORMS** (Agent 01's own tool, fresh clone, @ `247c036`).
- **Golden re-baseline.** All 13 `inputs_hash` values and the `config_hash` are unchanged under MBOS-CJSON-1. Only the version string and the ids seeded by it changed: no number, no verdict. The 13 goldens replay.
- **FYI Agent 01 (not lane C):** in the same interop run, row 06 reported "not found on branch" and row 07 reported 8/10.

### C-03 result (DONE @ `22b49e6`; receipt `docs/receipts/2026-10-07-c03-versioned-ids.md`)
- The v1.1.0 schemas now have versioned `$id`s: `https://michael-business-os/schemas/agent-03/v1.1.0/{opportunity,service-job,scorecard}.schema.json`.
- They coexist with the v1.0.0 copies Agent 01 vendored.
- Goldens and estimated Items validate against both frozen Item v1.0.0 and v1.1.0.
- 104 tests pass.
- **Agent 01:** re-vendor @ `22b49e6` under ADR-0009 item 6.

### C-04 result (DONE @ `882c726`; receipt `docs/receipts/2026-10-07-c04-sold-comps-feed.md`)
- `comps_feed.research_step` runs: Agent 02 SoldComp records + FACT provenance → fail-closed selection → bundle → estimate → score.
- **Acceptance:** the 02-fixture trailer goes RESEARCHING → SCORED, with 5 FACT comp research entries. All 11 decoys are rejected, each with its reason.
- **Hand-off:** Agent 02 owns the sources (`mbos_discovery.comps`); 03 owns selection.
- 118 tests pass.

### C-05 result (DONE @ `6e938d2`; receipt `docs/receipts/2026-10-07-c05-r13-pass-on-priors.md`)
- `scorecard.pass_on_priors` and `scorecard.pass_basis` implement R13. Engine 0.3.0.
- **Golden:** the priors-only mower PASS is flagged; the attested-price truck PASS is not.
- 127 tests pass.
- **Concern for Agent 01:** literal "at least one" is weak for flips, because the FACT ask almost always qualifies. A stricter variant is proposed in the receipt.

### C-06 result (DONE @ `9e36ec9`; receipt `docs/receipts/2026-10-07-c06-r13-amended.md`)
- **R13 amended:** a flip economic PASS needs the revenue side AND at least one cost-side input evidence-backed. Decisive inputs are arithmetic inputs only (corrects C-05, which counted the ask). Engine 0.4.0.
- **New golden:** the welder (02 listing + FACT sold comps) floor PASS on prior repair costs is flagged.
- **Interpretation note:** the revenue requirement is applied to economic gates only; see the receipt. Agent 01 can widen it in one line.

### C-07 result (DONE @ `0c3cf4a`; receipt `docs/receipts/2026-10-07-c07-learn.md`)
- `learn.load_outcomes` reads 04's read views (SELECT-only) and `calibrate` computes Brier/MAPE/bias.
- `propose_learn_bump` produces a tier-0 `config.scoring.bump` ActionRequest draft. Its payload embeds the whole next document, and `payload_hash` binds the approval.
- **Never applied:** the priors file stays byte-identical (tested).
- **Acceptance:** 2 outcomes yield a priors 2026.10.2 → 2026.10.3 proposal with provenance. 142 tests pass.

### C-08 result (DONE @ `a81a989`; receipt `docs/receipts/2026-10-07-c08-morning-digest.md`)
- `digest.build_digest(items, as_of)` is a pure, shuffle-invariant ranking. Each row has a reason, an action and provenance refs.
- Over the 14 goldens and 10 fixtures it gives 17 rows and 7 listed exclusions.
- CLI: `digest --text` for the 72-hour plan.
- Agent 06 renders it and must escape `title`.

### C-09 result (DONE @ `286e0f3`; receipt `docs/receipts/2026-10-07-c09-sensitivity-report.md`)
- `docs/research/agent-03-sensitivity-michael-decisions.md` is a report only; config untouched (hash-checked).
- **Main findings:**
  - The flip target is the most sensitive setting: the round-one trailer is YES only at ≤ $62/h.
  - The cash cap binds on vehicles: project car ≥ $1,400, truck ≥ $3,000.
  - The service target is coupled to quote-rate decision #6.

### C-10 result (DONE @ `e1869f2`; receipt `docs/receipts/2026-10-07-c10-asking-comps.md`)
- The asking-comp KeyError is fixed. The fix predates the queue entry because Agent 02 reported it directly.
- B-08 is green per Agent 02.
- **Also fixed (`4a93582`):** a stale `economics/build/` had been committed in `1044ed5`. It is now untracked and guarded by a test.

### C-11 result (DONE @ `c648ca3`; receipt `docs/receipts/2026-10-07-c11-estimator-coverage.md`)
- 19/19 categories either estimate or return an explicit blocking gap. Priors 2026.10.3, package 0.7.0.
- Vocabularies now cover every named flip category.
- `other_*` categories estimate only with human scope overrides.
- Fixed: scope overrides now feed the quote and hold-day computations.

### C-12 result (DONE @ `d5daf42`; receipt `docs/receipts/2026-10-07-c12-replay-audit.md`)
- `replay_audit.audit` is read-only. It covers `inputs_hash`, config, verdict, byte replay and ledger receipts.
- **Zero drift** on the 14 goldens and on a REAL lane-D export: 19 Items written via Agent 04's StateStore into a throwaway PG16 cluster, with `verify_chain` ok.
- Every planted drift kind is detected. Package 0.8.0.

### C-13 result (DONE @ `0d417fb`; receipt `docs/receipts/2026-10-07-c13-release-gate-hook.md`)
- The gate command is `python -m mbos_economics audit --dsn "$MBOS_DSN"` (exit 0/1/2). It is documented with expected output in `docs/research/agent-03-release-gate-at1.md`.
- 01's spine receipts lack `payload_hash`, so they are reported as `receipt_weak` (not drift). `--strict` fails them.

### C-14 result (DONE @ `ec97bf7`; receipt `docs/receipts/2026-10-07-c14-learn-lane-d.md`)
- Outcomes recorded by Agent 01's real `spine_d.record_outcome` flow into `load_outcomes`, `calibrate` and a tier-0 proposal. The lane-D store refuses the proposal (`item_id` NOT NULL, the ADR-0009 item 9 gap); nothing is applied.
- The LEARN provenance must be persisted before a proposal is submitted (the first attempt hit "unknown provenance ids").
- The test needs `MBOS_LANE_D_STATE_DIR` and skips cleanly without it. 195 pass with the lane-D environment, and 193 pass with 2 skipped without it.

### C-15 result (P0; DONE @ `2575ed3`; receipt `docs/receipts/2026-10-07-c15-deal-sniffer-enrichment.md`)
- `enrich.build_enrichment` produces the `economics`, `logistics`, `seasonality` and `why` blocks with basis and provenance on every datum. Anything the evidence cannot support is omitted (the card shows UNKNOWN).
- Transport is an economic input in the scoring arithmetic, never a gate. A trailer-requiring zero-turn mower scores and stays recommendable.
- Seasonality is sourced from web-search summaries (pages not read; owner-stated entries marked RECOMMENDATION). Concrete saw vs riding mower differ.
- The real `mbos.card.validate_card` is clean. 229 tests pass.
- **Agent 01 action:** pass `profile=` to `research_step`, and persist `e["provenance"]` before attaching the blocks.

### C-16 result (DONE @ `c88cd5a`; receipt `docs/receipts/2026-10-07-c16-value-add.md`)
- `valueadd.build_value_add` produces the `value_add` block: a plan from the deal's own numbers, plus risks from a sourced knowledge base.
- The KB holds six CPSC recall entries, each read on its primary agency page on 2026-10-07 (via a summarizing fetch tool). It has no general advice.
- A risk appears only when a make AND a model token match the listing. No match means no risks, and the card shows UNKNOWN.
- The GP7500E is verified NOT on the Generac recall.
- The real `mbos.card.validate_card` is clean. 253 tests pass.

### C-17 result (DONE @ `3569efb`; receipt `docs/receipts/2026-10-07-c17-model-knowledge-and-manual-notes.md`)
- Source plan: `docs/research/agent-03-model-knowledge-source-plan.md` (admission standard, 7 ranked routes with verified vs unverified marked, ownership).
- `manual` path: Michael's notes enter with a human provenance record, always as RECOMMENDATION (never FACT), make AND model required, elementary advice refused. `load_kb` refuses manual entries, so nothing unsourced can ship. CLI `note new` / `note check`.
- 278 tests pass (267 by default).

### Review of Agent 02's B-16 CPSC converter (not a queued task; done @ the commit after `8cdfa92`)
- **Verified:** its claim holds. My real `load_kb` accepts all 3 entries it generates from its fixtures, and its review list is sensible.
- **Found, a false-positive risk in its token extraction:** bare numbers (`6500`, `8000`, `2018`) pass as "models". A Northgate "6500 watt" listing of a NON-recalled model then matched a recall entry, which is a false safety claim.
- **Fixed on my side (fail closed, whatever the source):** `load_kb` now refuses an entry with a purely numeric or under-3-character model token, or a match group without both makes and models. Package 0.10.1; 283 tests pass.
- **Found, a false-negative bug in its extraction:** `model_tokens("Model 17AWCBYS010 and 17AWCBYZ010")` returns only `['17AWCBYZ010']`, so the label word "Model" makes the first model silently drop. Sent to Agent 02 with a suggested fix.

### Review: D-17 operator-note store (Agent 04 @ `77d1f17`): ACCEPTED (receipt `docs/receipts/2026-10-07-d17-acceptance-review.md`)
- 8 acceptance tests against a real 0016 database, connected as each role, using my real `new_manual_note` / `load_manual_notes` / CLI. The folded document passes `note check` (exit 0) and the roles behave.
- **My bug found and fixed:** a retracted note's copied text was still linted, so retraction could not clear a bad note. Retracted notes are now skipped. I also added `load_manual_notes_lenient`, so one bad note no longer disables the rest.
- **Documented limitation:** the DBOS worker login inherits `approver` and can record notes (by design; no LLM-facing process uses it). Pinned by a test.
- Package 0.10.2; 294 tests pass with all environments.

### C-18 result (DONE @ `d9bceea`; receipt `docs/receipts/2026-10-07-c18-model-years.md`)
- `match[].years` (list, range or `"2010-2014"`): a year-specific entry applies only when the LISTING states a covered year (read from the title: inference, evidence shown). A yearless listing never matches; every blocked match is recorded as UNKNOWN in `year_blocked` and `omitted`.
- Preserved: the numeric-token asymmetry. Yearless entries behave exactly as before.
- 318 tests pass with all environments.

### Verified: Agent 02's B-18 NHTSA entries (not a queued task)
- Ran its recall and complaint entry builders over its fixtures through my real `load_kb` and `match_hits`. Its report holds: a 2012 listing hits its 2012 entries; 2013 hits only the 2013 recall; 2018, yearless and "2012 and 2018" listings hit nothing and show as blocked; the Mazda "3" stays held.
- **Gap found on my side:** `load_kb` accepted two entries with one id, which would collide in the matched list and in the year evidence (keyed by id), attaching the wrong year to a safety claim. It now refuses duplicate or missing ids (package 0.11.1; 321 tests pass with all environments).

### Queue check 2026-10-08 (READY_QUEUE @ agent-01 `2f7b887`)
- **No new lane-C task.** Open rows naming 03: C-14 (stale, see below) and X-03.
- **C-14 row is stale:** the queue still shows it READY, but it is DONE @ `ec97bf7` (receipt `docs/receipts/2026-10-07-c14-learn-lane-d.md`). The queue's sync note lists my branch at `73a4d32`. Not redone.
- **X-03 (all lanes; remove committed `build/`): already satisfied.** The branch tracks no `build/`, `dist/` or `egg-info` at any depth (checked on `origin/research/agent-03-economics`). My nested `economics/build/` was removed at `4a93582`, and `.gitignore` covers `build/` and `dist/`. A clean `git archive` + pip install reports 0.11.1. A test (`test_git_tracks_no_build_output`) guards it.

## Proposed tasks (for Agent 01 to triage)
- P-03-14 (found in C-22): `plan_week` output fails coordinator A-33 `mbos.mission.plan_errors` in 2 cases (HOLD/UNKNOWN plan with legs committing cash; projected_week.low 0.0 not supported by legs). Fix lane-03 planner or vendor-test expectations. Acceptance: test_mission passes with `mbos` on PYTHONPATH.
- **P-03-10 (lane C): C-22 Valuator interface + FlipComparablesValuator** (READY in the queue; not started). Acceptance: mower and trailer fixtures produce `valuation.schema.json` ranges with evidence and `not_an_appraisal: true` that pass `mbos.valuation.errors`; asking-only comps cap confidence at medium; sold comps or a record allow high; home and vehicle valuators are interface-only and return UNKNOWN with `reason_unknown`, never a number; reuses `comps.py` / `comps_feed.py` / `estimation-priors.json`.
- **P-03-11 (lane C): fill the new numeric context from data.** The estimator should set `economics.context.seasonality_factor` from `seasonality.json` (needs a human-read source for each category; today UNKNOWN) and accept Michael's `current_cash` from `config/operator_profile.v1.json` `current_cash_context`. Acceptance: with the profile cash set, the late-season mower row shows cash pressure; with it null, the row says UNKNOWN; seasonality is only set where a sourced entry exists.
- **P-03-12 (lane C + owner): confirm deal-class thresholds (MICHAEL_DECISIONS #9).** `scoring-config.json` `deal_classes` / `class_gates` mirror the operator profile and are PROVISIONAL. Acceptance: once Michael answers, a config bump (2026.10.3+) with the history copy, the drift test `test_config_classes_mirror_operator_profile` green, goldens regenerated.
- **P-03-13 (lanes C + D + F): feed `plan_week` real data.** Read scored Items from the StateStore (`mbos.v_item_documents`) and the capital ledger (D-18) into `plan_week`, and expose `mission plan` on the CLI. Acceptance: a plan generated from the database validates with `mbos.mission.plan_errors` and every leg links to its card.
- **P-03-08 (lane B): CPSC knowledge adapter.** Read the CPSC programmer's guide (response fields, rate limit), then a read-only, fixture-first Tier-1 adapter emitting recall records. 03 supplies the deterministic record-to-KB-entry converter once the fields are known.
- **P-03-09 (lanes F + A): "Add what you know about this model" prompt on cards that show no sourced knowledge**, and a store for the notes document (persist the human provenance first, then the note).
- **P-03-07 → queued as C-17.** Original: a source plan for non-recall model knowledge (known weak points, expensive parts, parts availability). My searches found nothing citable for the Cub Cadet ZT1 or the Husqvarna FS 400 LV. Routes: service bulletins, manufacturer parts diagrams, and Michael's own notes entered with provenance as `manual`.
- **P-03-06 → DONE by Agent 01 @ `ca6d056`** (the spine writes `payload_hash`; the gate can use `--strict`). Original text:
  - Set `payload_hash = sha256_of(scorecard)` (MBOS-CJSON-1) in `spine_d.record_score`'s receipt `extra`.
  - The ledger then binds the scorecard content, not just its inputs, and the release gate can run `audit --strict`.
- **P-03-05 → accepted as ADR-0009 item 9** (agent-01 `edbc492`). Original text:
  - Frozen v1.0.0 requires `item_id` and has no config category.
  - The C-07 draft omits `item_id` and uses `config_change`, and conforms otherwise.
  - Request: make `item_id` optional for system actions, and add the `config_change` category (tier 0).
- **P-03-03 (lane C, internal): ship config as package data. DONE** (see the commit after `7390416`).
  - `economics/config/` moved to `economics/src/mbos_economics/config/` and is declared as package-data.
  - A non-editable wheel install, used from an unrelated directory, loads config 2026.10.1, history and priors, and replays a golden (`match: true`).
  - Original report:
  - Agent 02 reported that the installed `mbos_economics` wheel has no `config/`, so callers like A-05 need a pinned copy.
  - Fix: config moves inside the package. Agent 02's adapter-side workaround becomes unnecessary.
- **P-03-04 → accepted as amended R13, implemented as C-06 (DONE).** Original text: Require the revenue side and at least one cost-side input to be evidence-backed (see the C-05 receipt).
- **P-03-01 → queued as C-04, DONE.** (Original text kept below for the record.) Sold-comps feed. Every real flip from eBay Browse (active listings only) stays `insufficient` until a sold-comps source exists. Options for 02:
  - eBay Marketplace Insights (restricted access)
  - completed-auction feeds from GSA and other auction sites (B-03)
  - manual comps entry through the Operator UI, with provenance

  03 already consumes `bundle.comps[]` with `kind: sold|asking`.
- **P-03-02 (lanes A + C): routing of prior-only PASS.** A PASS that rests only on category priors (no evidence) archives a lead that was never researched. Option: route a PASS whose `evidence_search` shows evidence could lift it to MAYBE/RESEARCH. This is a routing choice for Agent 01, not an engine change.

## Current objective
Deliver the deterministic, replayable economics and scoring engine for both lanes (FLIPS + SERVICES), built against the frozen contracts v1.0.0 (ADR-0004) and the ADR-03-001 binding changes. **Done.** Next: integration with lane A (01) and lane D (04).

## Inputs read (round two)
- FACT: own round-one research @ `b032676`.
- FACT: `origin/research/agent-01-coordinator` @ `acb6f3b`:
  - `agent-01-integration.md`: C13, C14, §8 C-suite, §10 gap list
  - `ADR-0004`
  - `INDEX.md` (ADR-03-001 = ACCEPTED-WITH-CHANGES)
  - `MICHAEL_DECISIONS.md`
  - `contracts/`

## Completed (round two)
- **Engine** `economics/` (v0.1.0; Python ≥3.10; stdlib-only; Decimal arithmetic):
  - gates first, then the composite floor, then YES conditions → YES / MAYBE / PASS
  - an alert only when the deal is strong **and** perishable
  - Computes: travel cost and time, parts, materials and repair cost, buy/sell/payment fees, storage and disposal, cash tied up, expected revenue, expected net, profit/hour (deterministic and EV), ROI, confidence, risk (max loss, P(loss), CoV), time-to-cash, skill fit, scarcity / lead quality.
  - **Extras that make the verdict actionable:**
    - `walk_away_price`: the flip offer ceiling for YES
    - `min_quote_for_yes`: the service quote floor
    - `cheapest_decisive_evidence`: EVPI-lite, cheapest first
- **Versioned config** `economics/config/scoring-config.json` **2026.10.1**:
  - single source of truth; per-mile cost is derived (C13)
  - the 2026.10.0 file is archived in `config/history/`
  - Coordinator defaults sit in config, tagged `source: MICHAEL_DECISIONS`: $1,500 cash/deal, $800 max loss, $40/h floor, $65 flip / $75 service targets.
- **Replay and identity:**
  - `inputs_hash` (sha256 of canonical input + config version)
  - deterministic ULID-shaped `scorecard_id` / `rec_` / `prov_` ids (no clock, no randomness)
  - `config_hash` stored; `replay_item()` plus a CLI
- **Provenance and receipts.** `score_item()` emits:
  - a Provenance v1 record (tool + version + config + input hashes + upstream provenance ids)
  - `SCORE_RECORDED` and `RECOMMENDATION_RECORDED` receipt drafts with `payload_hash` and an idempotency key, for 04 to commit in the same transaction
- **C14 resolved.** The rule was kept and AT-14 corrected. The §17.1 trailer is MAYBE (EV $62.02/h < $65), with walk-away $227. At $225 it is YES + ALERT.
- **Gap list, 03 rows 1–6:**
  - (1) C14
  - (2) missing inputs added, schemas v1.1.0 (additive)
  - (3) `buy_fees` on services; `lead_quality` deliberately absent on flips (documented)
  - (4) `inputs_hash` / `scorecard_id`
  - (5) worked examples
  - (6) LEARN config-bump flow (`learn.propose_config_bump`: tier-0 ActionRequest draft, never self-activates)
- **Worked tests:**
  - FLIPS: trailer ×2, mower ×2, generator, project vehicle ×2, plus 01's trailer example
  - SERVICES: drywall, smart-home ×2, equipment repair, plus 01's drywall example
- **Acceptance:** AT-1..AT-21 (AT-14 corrected), C22, C23, contract conformance, determinism. **75 tests pass** (pytest, and stdlib unittest on 3.10 and 3.12). The 13 golden scored Items replay byte-identically across Python versions.
- **Docs:**
  - `docs/decisions/ADR-03-002-round-two-engine.md` (PROPOSED)
  - `docs/research/agent-03-worked-examples.md`
  - `economics/README.md`
  - `docs/receipts/2026-10-07-round-two-engine-build.md`
  - errata in the round-one research doc

## Findings
- FACT: round one's AT-14 contradicted its own §12.4 rule (C14). Round one's mower claim ("survives gates; → MAYBE with evidence") was also wrong, because deterministic $39.84/h is below the $40 floor. Both are corrected.
- FACT: 01's illustrative trailer example (`contracts/examples/item-flip-trailer.example.json`) scores **PASS**, not the recorded YES/61.6:
  - it has no evidence block, so confidence is 0.20
  - EV is $44.95/h
  - composite is 43.06

  01's drywall example scores MAYBE, as recorded. Corrected, engine-scored versions are in `economics/examples/`.
- FACT: the stored round-one `v` = $0.46/mi had drifted from its own parts (3.20/18 + 0.28 = 0.4578). It is now derived.
- INFERENCE: EV profit/hour against target blocks YES in all 3 MAYBE cases and is the only blocker in 2 of them. The walk-away price and minimum quote turn a MAYBE into a concrete negotiating number.

## Unknowns
- UNKNOWN: Michael's real cash cap, max loss, $/h floor and targets (MICHAEL_DECISIONS #1/#2). The coordinator defaults are in use.
- UNKNOWN: home base, vehicle mpg and wear, local fuel price (config UNK tags).
- UNKNOWN: licenses Michael holds (`skills.licenses_held` = []); the license-gated list needs Agent 05's authoritative version.
- UNKNOWN: skill proficiency levels are REC priors until outcomes exist.
- UNKNOWN: item-side basis tagging of estimates (AT-2, item half) depends on Agent 02's normalization output.

## Blockers
None.

## Needs Michael decision
- **Service pricing policy (new, not blocking):** the hourly quote rate (placeholder $85/h, all-in) and the minimum job charge (placeholder $125). These are in `estimation-priors.json` as UNK.
- MICHAEL_DECISIONS #1 (cash per deal / total) and #2 ($/h floor / targets). They are not blocking: defaults are in config and a change is a version bump, not code.

## Needs coordinator review
- **ADR-03-002** (PROPOSED):
  - the C14 resolution (rule kept, test fixed)
  - formula clarifications F1–F11
  - the `inputs_hash` scope extended to `type`/`category`/distance
- **Re-vendor** `docs/research/schemas/*.schema.json` v1.1.0 into `contracts/vendor/agent-03/`. The change is additive and `$id`s are unchanged, so Item v1 `$ref`s still resolve.
- **C23:** replace or annotate `contracts/examples/item-flip-trailer.example.json`. Its recorded scorecard does not reproduce. The engine-scored version is `economics/examples/trailer_enclosed_coordinator.scored.json`.
- **Integration (lane A/D):** call `score_item(item, cfg, scored_at)` inside the SCORE step. 04 commits the scores, provenance and receipt drafts in one transaction.

## Files produced (round two)
- `economics/` (package, config, history, tests, examples, scripts, README)
- `docs/decisions/ADR-03-002-round-two-engine.md`
- `docs/research/agent-03-worked-examples.md`
- `docs/research/schemas/{opportunity,service-job,scorecard}.schema.json` (v1.1.0)
- `docs/research/config/README.md` (pointer; the old json was moved to history)
- `docs/receipts/2026-10-07-round-two-engine-build.md`

## Notes
- FACT: the shared git config on this machine is set to "Agent 07 Marketing". Agent 03 does not modify the shared config; round-two commits pass an Agent 03 identity per commit.

## Next action
Wait for Agent 01 review of ADR-03-002 and integration wiring. On request:
- wire to 02's normalized fields
- tune config once Michael decides #1/#2 (a version bump)
- extend LEARN once 04's outcome store exists

## P-03-16
Done: P-03-16 @ 0e985dc (lane-03 side: `build_value_add(model_years=)`; 355 passed, 22 skipped). State: CLOSED

## P-03-17
Done: P-03-17 @ 276ecd4 (plan_from_documents skips malformed-scorecard Items, names them in `unknowns`; 356 passed, 22 skipped). State: CLOSED
Proposed (for 01): in `src/mbos/adapters/economics.py` `_value_add`, pass `model_years=extract_model_years(title)` to `build_value_add` (coordinator-branch file), then run card lint.

## C-24
Done: C-24 @ 6b8d9d4 (caps 1500/800 -> 500/500, available_to_deploy honoured, config 2026.10.4; 359 passed, 22 skipped). State: CLOSED

## C-26
Done: C-26 @ 3d0fd86 (consumer_electronics/small_goods priors via other_asset vocabulary, listing facts kept, true gap text; 377 passed, 22 skipped). State: CLOSED

## C-27
Done: C-27 @ f63011e (part b: human scope overrides read from Item.research `scope_override:*` into the estimator as human-attested overrides; 381 passed, 22 skipped). State: CLOSED
Partial: part (a) service quote input not built (needs where the quote lands + MICHAEL_DECISIONS #6). Proposed for 01/04: a `record_scope_override` spine helper writing the research entry shape in the receipt; then 06 adds the form.

## C-28
Done: C-28 @ 96cb704 (service quote: Item.research `quote:amount_usd` -> `job.quoted_revenue` human-attested; drywall lead with attested scope+customer: $700 YES, $500 MAYBE; 387 passed, 22 skipped). State: CLOSED

## C-30
Done: C-30 @ 9792ca7 (owned_asset five-path comparison on incremental cash, sunk basis excluded, UNKNOWNs named, past tow stays INFERENCE; 394 passed, 22 skipped). State: CLOSED
Proposed for 01/06: F-34 calls `mbos_economics.owned_asset.compare_paths(item, as_of)`; Item type enum may need `owned_asset` (contract, ADR) if it should pass schema validation.

## C-29
Done: C-29 @ 6f978de (LEARN groups other_asset TVs/small goods by prior class so non-zero consumer_electronics priors calibrate; proposal stays tier-0 drafted; 396 passed, 22 skipped). State: CLOSED

## C-31
Done: C-31 @ 6a826aa (readers accept value/author from `finding` JSON as well as old extra fields; $700 YES / $500 MAYBE from new shape; 402 passed, 22 skipped). State: CLOSED

## C-32
Done: C-32 @ c0e98d2 (auction cost model: premium/tax/pickup/transport all-in, time to cash, turns, $/labor-hour, 24/48h and slow flags, asking-only never YES; additive auction-model.json; 410 passed, 22 skipped). State: CLOSED

## C-33
Done: C-33 @ PENDING (asset_deal module: parts-out donor value, component machine paths, untitled-trailer paperwork, profit/day, capital tied/at risk, max bid, labelled bid forecast, owner override with provenance; 422 passed, 22 skipped). State: CLOSED
