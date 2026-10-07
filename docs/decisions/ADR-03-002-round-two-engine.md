# Decision

**ADR-03-002: Round-two economics engine. Resolves C14, implements the ADR-03-001 binding changes, and pins determinism rules**

Status: PROPOSED (Agent 03, 2026-10-07). Agent 01 gives the disposition.

Supersedes nothing. It implements ADR-03-001 (ACCEPTED-WITH-CHANGES, `INDEX.md`) and answers the 03 gap list in `agent-01-integration.md` §10.

## Context

ADR-03-001 was accepted on condition that 03:
- fixes the §17.1 vs §12.4 contradiction (C14)
- adds the missing formula inputs
- adds `inputs_hash` and `scorecard_id`
- keeps every threshold as config pending MICHAEL_DECISIONS #1/#2
- keeps `scoring-config.json` as the single source for per-mile cost (C13)

Round two requires a deterministic, testable implementation for both lanes. No LLM may do the final arithmetic.

## Decisions

### 1. C14: keep the rule, fix the test (FACT: implemented; tests AT-14, `TestTrailerUtility_C14`)
- **The rule stands.** A YES requires EV profit/hour ≥ `w_target` ($65 flip / $75 service). This is checked after all hard gates pass.
- **Round one's AT-14 was wrong.** With the round-one §17.1 inputs, the trailer is **MAYBE**:
  - EV profit/hour is $62.02, below the $65 target.
  - Alert is false, because an alert requires YES.
- **The engine now says what fixes it.** It reports `walk_away_price = $227`. At a $225 buy the same trailer is YES + ALERT (EV $65.36/h).
- Why keep the rule (RECOMMENDATION):
  - The target is an owner-policy number (MICHAEL_DECISIONS #2). Exempting a "legitimately strong deal" by hand is exactly the discretion the engine exists to remove.
  - If trailers reliably beat their estimates, LEARN lowers the target or the haircut through a config bump that Michael approves (§6). The rule is not bent in code.
- Round one also mis-stated the mower. The engine assigns **PASS**: deterministic $39.84/h is below the $40 floor, so the floor gate fails. Round one claimed it "survives gates" and becomes MAYBE with evidence. With the compression evidence the mower is still PASS, because evidence does not change hours or cash. A floor is a floor.

### 2. Gates first, score second (FACT: `engine.compute`)
**Step 1: hard gates.** Any single failure gives PASS. Every failure is listed in `gates` and `reasons`.

| Gate | Passes when |
|---|---|
| `ev_positive` | `ev_decision` > 0 |
| `max_loss_ok` | max loss ≤ $800 |
| `cash_ok` | cash tied up ≤ $1,500 |
| `skill_ok` | `skill_fit` ≥ 0.40 |
| `license_ok` | no license-gated skill is required, and `requires_license_he_lacks` is not set |
| `pph_floor_ok` | deterministic profit/hour ≥ $40 |
| `min_profit_ok` | deterministic net ≥ $150 flip / $100 service |
| `distance_ratio_ok` | beyond 60 mi one-way only: (trips cash + travel h × $40 + wasted-trip EV) ≤ 0.35 × EV net |

**Step 2: composite floor.** A composite below 45 gives PASS.

**Step 3: YES conditions.** All of these together give YES; otherwise the verdict is MAYBE, with every blocking condition named.
- composite ≥ 60
- confidence ≥ 0.60
- EV profit/hour ≥ target
- EV after haircut ≥ min profit
- beyond 60 mi: remote verification
- flips only: ≥ 3 sold comps, fault identified, and title verified for titled categories (trailer, project_vehicle)

**Step 4: alert.** An alert needs YES **and** a perishable deal (research §12.5). The service lane uses lead quality ≥ 0.6, lead age < 6 h, and EV ≥ 2× min profit.

### 3. Formula changes vs round one (INFERENCE: each is a correction or a disambiguation, listed so nothing changes silently)

| # | Round one | Round two | Why |
|---|---|---|---|
| F1 | `v` stored as 0.46 | `v` derived = fuel/mpg + wear = **0.4578** | C13: one source; a stored 0.46 had drifted from its own parts |
| F2 | fail branch charged all trip cash | fail branch charges **acquisition-side trips only** (not `buyer_meet`/`deliver`) | a dead asset is never driven to a buyer |
| F3 | service EV = p·Net − cost_to_quote, where cost_to_quote included H·w | explicit 3-branch tree (won clean / won goes bad / lost bid). Quote cash is sunk in every branch. Quote **hours** go into expected hours, not into dollars. `cost_to_quote` is reported for display only | consistency with AT-4: Michael's time is never a cash cost |
| F4 | service CashTiedUp = max(0, M − deposit) | max(0, **all cash out** − deposit) | same definition as for flips (peak cash before inflow) |
| F5 | ratio gate (§13-1) stated generally | applies **only beyond 60 mi** (`distance_ratio_gate_beyond_miles`) | inside the radius, travel is already priced through cash and $/h. Applied everywhere it would PASS ordinary local deals |
| F6 | haircut applied to any EV | haircut applies only to a **positive** pre-haircut EV | otherwise low confidence would shrink a loss, rewarding ignorance |
| F7 | service confidence used the flip checklist | separate **service checklist** (scope, customer, written price, skill, materials, access, referral) | comps and title do not apply to services |
| F8 | N/A checklist items | title counts as satisfied for **untitled** categories | otherwise mowers could never reach full confidence |
| F9 | unknown scarcity inputs unspecified | unknown inputs earn **0** (deal discount, demand, supply, lead quality) | missing evidence earns no credit |
| F10 | MaxLoss over all branches | over branches with **probability > 0** | a branch that cannot happen is not a risk |
| F11 | formulas as prose strings in config | numeric parameters (`p_waste_*`, `haircut_*`) | config is data, not code |

### 4. Determinism and replay (FACT: implemented; AT-1, C22, cross-version replay)
- **Arithmetic.**
  - `decimal.Decimal` only. Input floats are converted through their string form, and numeric strings are rejected as input.
  - Each stored intermediate is quantized when it is computed: money 2 dp, hours, probabilities and ratios 4 dp, scores 2 dp, half-up. Later steps use the quantized value, so a person replaying the stored `derived` numbers reaches the same gates.
  - Probabilities are never rounded (exact Decimal products).
- **`inputs_hash`** = `sha256` of canonical JSON of `{spec: "mbos.economics.inputs/v1", scoring_config_version, input}`.
  - `input` = `{type, category, road_miles_one_way, economics, research_ids(sorted)}`, which is everything the numbers depend on.
  - Canonical JSON: keys sorted, no whitespace, numbers normalized (`3.2 == 3.20`).
  - This extends ADR-0004's "economics + research ids + version" with `type`, `category` and distance, which the arithmetic reads.
- **IDs** (`scr_`, `rec_`, `prov_`) are ULID-shaped and **derived**:
  - the 48-bit time part comes from the caller-supplied `scored_at`
  - the 80-bit tail is sha256 of `(inputs_hash | engine_version | scored_at)`
  - The engine never reads the clock or a random source (a test enforces this). The same inputs at the same `scored_at` produce the same IDs.
- **Replay** loads the stored `scoring_config_version` (current file or `config/history/`), re-derives the input from the Item, re-scores at the stored `computed_at`, and requires byte-identical canonical output.
  - `config_hash` is stored, so a config edited without a version bump is detected.
  - The 13 golden examples were generated on Python 3.12 and replay identically on 3.10.

### 5. Missing inputs added (gap item 2/3; schemas v1.1.0, additive and optional, `$id` unchanged)

**Flip:**
- `acquisition.market_buy_median`, `listing_age_hours`, `auction_ends_in_hours`, `acquire_lead_days`
- `rehab.requires_license_he_lacks`, `repair_days`
- `resale.active_comparable_listings`
- `estimates_meta.evidence{…, evidence_quality, remote_verification}`

**Service:**
- `job.buy_fees`, `payment_fee_rate`, `payment_fee_flat`, `disposal_cost`, `estimate_hours`, `schedule_lag_days`, `job_days`, `lead_age_hours`, `requires_license_he_lacks`
- `estimates_meta.evidence{…}`

**Other gap items:**
- `cost_to_quote` is **derived**, not input (F3).
- Skill-proficiency store: `skills.proficiency` in config. LEARN updates it only through a version bump.
- `lead_quality` on flips: **intentionally absent**. Flips use scarcity; seller quality is the `seller_screened` evidence item.

### 6. LEARN config-bump approval flow (gap item 6; FACT: `learn.propose_config_bump`, AT-17/18)
1. Outcome v1 `predicted_vs_actual` feeds Brier, MAPE and a beta-binomial shrink of priors.
2. `propose_config_bump(cfg, changes, rationale, evidence_refs, proposed_at)` returns the next config document (version `YYYY.MM.n+1`, changelog appended), a diff, its `payload_hash`, and an ActionRequest draft:
   - capability `config.scoring.bump`
   - **tier 0**
   - reversible
   - evidence refs required
   - It writes nothing.
3. Michael decides in the Operator UI.
4. On YES, the State lane (04) archives the current file to `config/history/`, writes the new one and emits `CONFIG_VERSION_BUMPED` in the same transaction. Old scorecards keep replaying under their own version (AT-17 test).

### 7. Integration surface (for 01 / 04)
- `score_item(item, cfg, scored_at)` returns:
  - `scores{scorecard_id, inputs_hash, scorecard}` and `recommendation{…}`, ready to place on Item v1
  - a `provenance` record (tool + version + config version + `inputs_used` hashes + `derived_from` upstream provenance)
  - two **receipt drafts** (`SCORE_RECORDED`, `RECOMMENDATION_RECORDED`), each with `payload_hash`, `inputs_hash`, a deterministic `idempotency_key` and `provenance_ids`
- 04's ledger adds `seq`, `prev_hash` and `row_hash`, and commits the drafts in the same transaction.
- The engine is pure. It does no I/O apart from reading the config, has no network access and makes no LLM calls.
- `recommendation.proposed_actions` is left empty. Turning a YES into ActionRequests belongs to the workflow, governed by 05.

## Consequences
- Every coordinator default is **config** (`source: MICHAEL_DECISIONS #n coordinator default`). Changing Michael's numbers means a config version bump, not a code change (test `test_policy_change_is_config_not_code`).
- 01's illustrative trailer example (`contracts/examples/item-flip-trailer.example.json`) does **not** score as recorded: it scores PASS, with composite 43.06, confidence 0.20 (no evidence block) and EV $44.95/h. The drywall example agrees (MAYBE). Corrected, engine-scored versions are in `economics/examples/`. 01 owns the contract examples and decides whether to replace them.
- The vendored 03 schemas in `contracts/vendor/agent-03/` are now one minor version behind (v1.1.0, additive). 01 should re-vendor them. The Item v1 `$ref`s keep resolving because `$id`s are unchanged.

## Reversibility
High for thresholds (config). Medium for formulas: an engine version bump, with old scorecards replayed by the old engine version, so the engine version is stored on every scorecard.

Coordinator review required: YES. C14 resolution, F1–F11, the `inputs_hash` scope, and a request to re-vendor the schemas and the corrected examples.
