# Agent Status

Agent: 03
Role: Economics / Scoring (Round-Two build lane C)
Branch: research/agent-03-economics
Worktree: /home/michaelos/business-os-worktrees/agent-03-economics
State: WAITING
Current phase: ROUND TWO, wave two. Claimed task: RESEARCH/estimate producer (lane C)
Started: 2026-10-06
Last updated: 2026-10-07 (C-05 done; P-03-03 done; WAITING: no READY lane-C task)

## Claimed work (wave two). Foreman loop: `docs/COORDINATION.md` @ agent-01 `99e9ec0`
Claimed: (none)
Done: C-01 @ 42fed5e; C-02 @ 247c036; C-03 @ 22b49e6; C-04 @ 882c726; C-05 @ 6e938d2
Queue (lane C): none READY @ agent-01 `0d107df`
Waiting on: Agent 01 triage of P-03-04 (tighten R13 for flips); A-05 / A-12 wiring questions (lane C will answer them)

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

## Proposed tasks (for Agent 01 to triage)
- **P-03-03 (lane C, internal): ship config as package data. DONE** (see the commit after `7390416`).
  - `economics/config/` moved to `economics/src/mbos_economics/config/` and is declared as package-data.
  - A non-editable wheel install, used from an unrelated directory, loads config 2026.10.1, history and priors, and replays a golden (`match: true`).
  - Original report:
  - Agent 02 reported that the installed `mbos_economics` wheel has no `config/`, so callers like A-05 need a pinned copy.
  - Fix: config moves inside the package. Agent 02's adapter-side workaround becomes unnecessary.
- **P-03-04 (lanes A + C): tighten R13 for flips.** Require the revenue side and at least one cost-side input to be evidence-backed (see the C-05 receipt).
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
