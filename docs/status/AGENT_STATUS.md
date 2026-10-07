# Agent Status

Agent: 03
Role: Economics / Scoring (Round-Two build lane C)
Branch: research/agent-03-economics
Worktree: /home/michaelos/business-os-worktrees/agent-03-economics
State: WORKING
Current phase: ROUND TWO, wave two. Claimed task: RESEARCH/estimate producer (lane C)
Started: 2026-10-06
Last updated: 2026-10-07 (wave two: task claimed)

## Claimed work (wave two)
- FACT: Michael's instruction names Agent 01's `READY_QUEUE` and `ACTIVE_WORK`. **Neither file exists** on any remote branch (`git fetch` then `git ls-tree` on every `origin/*`) or in the Agent 01 worktree, as of `origin/research/agent-01-coordinator` @ `bed7609`.
- The binding assignment source used instead is `docs/integration/ROUND_TWO_INTEGRATION.md` @ `bed7609`, §3C and §5.5.
- **CLAIMED, in progress:** `C-RESEARCH-01`, the RESEARCH/estimate producer. It fills `Item.economics` from normalized listing/intake fields, structured comps and category priors, so that lane-B Items can leave RESEARCHING.
  - Co-owner Agent 02 (comps data) has not claimed it (FACT: 02 status @ `5b62625`).
  - Contract: deterministic, no LLM arithmetic, every estimated field basis-tagged, and no sale price without comps (§14).
- **NEXT (queued, compatible):** `C-R3-01`, making `inputs_hash` and every 03 hash follow ruling R3's normative canonical JSON.
- **R1–R11 acknowledged.** No objection from lane C.

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
