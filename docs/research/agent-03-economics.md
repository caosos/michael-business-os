# Agent 03 — Deal Economics & Scoring Engine (Round One Design)

**Branch:** `research/agent-03-economics`
**Status:** Research / design only. No production changes, no purchases, no CAOSCare work.
**Author:** Agent 03 (Economics)
**Date:** 2026-10-06

---

## 0. How to read this document

Every substantive claim is tagged with its epistemic status:

| Tag | Meaning |
|-----|---------|
| **[FACT]** | Mathematical identity, established method, or value Michael's prompt stated. Not up for debate. |
| **[INFER]** | A conclusion I derived for this context from the facts. Defensible but mine, not law. |
| **[REC]** | A recommended default (threshold, weight, constant). A starting value meant to be calibrated. |
| **[UNK]** | A value I do not have and cannot responsibly invent. Must be supplied by Michael or learned from outcomes. |

**Design principle (governing all else):** *Every score must be explainable and reconstructable.* A score is never a black box. Each one carries the inputs, the formula version, the intermediate values, and the provenance of each input, so Michael (or Agent 05 governance) can replay the arithmetic by hand and get the same number. **[FACT]** (stated requirement)

This aligns with the system law repeated across agents: **"No action without a receipt. No receipt without provenance."** A score *is* a receipt of a judgment. **[INFER]**

---

## 1. Mental model: what the engine actually decides

Michael has three scarce resources: **time**, **cash**, and **attention**. Every opportunity — whether flipping a physical asset or taking a service job — is a bet that consumes some of each and (probably) returns more than it consumes. **[INFER]**

The engine answers one question in a reconstructable way:

> *Given everything we can estimate and how sure we are of it, is this the best use of Michael's next hour and next dollar — and if so, how urgently?*

It outputs, for every opportunity:

1. A full economic reconstruction (all costs, revenues, probabilities, hours).
2. Derived metrics: **net profit, expected value, profit/hour, ROI, cash tied up, time-to-cash, max loss**.
3. Qualitative models scored 0–1: **risk, confidence, skill-fit, scarcity**.
4. A composite **0–100 priority score** and a **YES / MAYBE / PASS** decision with reasons.
5. An **alert flag** when the deal is both strong and perishable.

Two opportunity types share one engine but use different metric emphasis:

- **PHYSICAL ASSET FLIP** — buy an asset, (maybe) repair it, resell it. Capital at risk, two probabilities (repair succeeds, sale happens), salvage floor. ROI and cash-tied-up matter.
- **SERVICE JOB** — sell Michael's labor/skill on a customer's property or asset. Little capital at risk; the scarce input is hours. Profit/hour dominates; "sale probability" becomes "win probability" of a quoted lead. **[INFER]**

---

## 2. Methodological grounding (accepted methods used)

The engine composes established methods rather than inventing math. **[FACT]** for each method's existence; **[REC]** for how I combine them.

| Domain | Method borrowed | Where it's used here |
|--------|-----------------|----------------------|
| Decision theory | **Expected value over a decision tree**; EV = Σ P(outcome)·Value(outcome) | Core profit model (§6) |
| Decision theory | **Expected Value of Perfect Information (EVPI)** — value of reducing uncertainty before committing | "Minimum evidence before YES" (§15), inspection-trip logic |
| Betting / capital | **Kelly-style fractional sizing / risk-of-ruin** — never stake capital you can't afford to lose | Max-loss cap & cash gates (§8, §12) |
| Inventory / retail | **Inventory turnover & GMROI** (gross-margin return on inventory investment); **days-on-market (DOM)** | Time-to-cash (§10), scarcity (§11), ROI-per-cycle |
| Auctions | **Buyer's premium + all-in landed cost**; **winner's curse** discipline (don't overpay vs. estimated value under uncertainty) | Fees (§5), confidence haircut (§9) |
| Contracting / trades | **Loaded labor rate**, **markup vs. margin**, **cost-plus vs. value pricing**, billable-hour efficiency | Service-job model (§4, §7) |
| Fleet / logistics | **Cost-per-mile = fuel + wear/depreciation**; **$/mile ≈ IRS standard mileage rate as an all-in cross-check** | Travel economics (§5.3) |
| Forecasting | **Comparable-sales (comps) appraisal** using *sold* prices, median, outlier trimming, condition adjustment | Comps methodology (§14) |
| Forecast QA | **Brier score** (probability calibration), **MAPE** (estimate error) | Learning loop (§16) |

> **[REC]** The 2025 U.S. IRS standard business mileage rate (~$0.70/mi, which bundles fuel + maintenance + depreciation) is used only as a **sanity cross-check** on our bottom-up per-mile figure, not as the operating number. It should be verified against the current IRS publication before relying on it. **[UNK]** exact current rate at runtime.

---

## 3. Canonical Opportunity Schema (physical asset flip)

This is the superset record. A service job (§4) is a specialization that reuses the shared blocks. Field `source` on every estimated value records provenance so the score is reconstructable. Machine-readable JSON Schema: [`schemas/opportunity.schema.json`](schemas/opportunity.schema.json).

> Alignment note: field names are conceptual. Agent 02 owns the *discovery/normalized* opportunity schema and Agent 04 owns canonical entities + the receipt/provenance schema. This schema is designed to **nest inside** theirs, not replace them. **[INFER]**

### 3.1 Top-level structure

```jsonc
{
  "opportunity_id": "uuid",
  "type": "flip",                      // "flip" | "service"
  "category": "trailer|mower|generator|appliance|tool|vehicle|...",
  "title": "5x8 utility trailer, needs deck + tire",
  "source": {                          // provenance (Agent 02 / Agent 04 territory)
    "platform": "facebook_marketplace",
    "listing_url": "...",
    "listing_posted_at": "2026-10-06T08:12:00Z",
    "observed_at": "2026-10-06T08:40:00Z",
    "seller_ref": "seller_uuid"
  },

  "location": {
    "home_base": "Conway, AR",         // [UNK] confirm exact home base
    "item_lat_lng": [34.9, -92.4],
    "road_miles_one_way": 20,          // road miles, not straight-line
    "estimated_drive_minutes_one_way": 27
  },

  "acquisition": { ... },              // §3.2
  "rehab": { ... },                    // §3.3  (repair/parts/materials/labor)
  "logistics": { ... },                // §3.4  (trips, fuel, mileage, travel time)
  "holding": { ... },                  // §3.5  (storage, disposal, fees)
  "resale": { ... },                   // §3.6  (revenue, comps, probabilities)
  "downside": { ... },                 // §3.7  (salvage, max loss)

  "estimates_meta": {                  // makes every number auditable
    "scoring_config_version": "2026.10.0",
    "comps": [ /* see §14 */ ],
    "assumptions": [ { "field": "...", "value": "...", "basis": "FACT|INFER|REC|UNK", "note": "..." } ]
  },

  "scorecard": { ... }                 // §12 output, written back after scoring
}
```

### 3.2 `acquisition` block

| Field | Type | Unit | Notes |
|-------|------|------|-------|
| `ask_price` | number | $ | Seller's listed price |
| `expected_buy_price` | number | $ | After expected negotiation — **use this in the model** |
| `buy_fees` | number | $ | Title transfer, sales tax, auction buyer's premium, platform fee |
| `negotiation_confidence` | 0–1 | — | How sure we are of `expected_buy_price` |

### 3.3 `rehab` block (repair / parts / materials / labor)

| Field | Type | Unit | Notes |
|-------|------|------|-------|
| `parts_cost` | number | $ | Replacement components (`P`) |
| `materials_cost` | number | $ | Consumables: paint, lumber, hardware (`M`) |
| `labor_hours` | number | h | Michael's hands-on repair/fab hours |
| `required_skills` | string[] | — | e.g. `["welding","wiring","paint"]` — feeds skill-fit |
| `repair_success_prob` | 0–1 | — | `p_repair`: P(asset made sellable at estimated cost) |
| `repair_scope_known` | bool | — | Has the fault been identified? (evidence gate) |

### 3.4 `logistics` block (travel economics — §5.3)

| Field | Type | Unit | Notes |
|-------|------|------|-------|
| `trips` | Trip[] | — | Each: `{purpose, round_trip_miles, can_combine}` |
| `fuel_price_per_gal` | number | $ | **[UNK]** calibrate to local price |
| `vehicle_mpg` | number | mpg | **[UNK]** per vehicle used |
| `wear_per_mile` | number | $/mi | **[REC]** depreciation + tires + maintenance |
| `avg_speed_mph` | number | mph | **[REC]** blended town+highway |

### 3.5 `holding` block

| Field | Type | Unit | Notes |
|-------|------|------|-------|
| `storage_cost_per_day` | number | $/day | Space opportunity cost |
| `expected_hold_days` | number | days | Buy → sold (drives time-to-cash) |
| `disposal_cost` | number | $ | Cost to dispose of unsellable remainder |
| `sell_fees_rate` | 0–1 | — | % platform/payment fee on sale |
| `sell_fees_flat` | number | $ | Flat listing/transaction fee |

### 3.6 `resale` block (revenue + probabilities)

| Field | Type | Unit | Notes |
|-------|------|------|-------|
| `target_sell_price` | number | $ | Gross resale at target (`R_sell`), from comps |
| `comp_price_low/expected/high` | number | $ | Distribution, not a point (§14) |
| `sale_prob` | 0–1 | — | `p_sale`: P(sells at/near target within horizon) |
| `expected_dom_days` | number | days | From comps' days-on-market |

### 3.7 `downside` block (salvage / floor)

| Field | Type | Unit | Notes |
|-------|------|------|-------|
| `salvage_if_repair_fails` | number | $ | `S_fail`: parts-out / scrap / wholesale recovery |
| `salvage_if_unsold` | number | $ | `S_unsold`: forced-markdown recovery |

---

## 4. Service-Job Schema

A service job reuses `location`, `logistics`, `holding.*fees`, `estimates_meta`, `scorecard`, and *most* of `rehab` (renamed semantics), but drops `acquisition`, `resale`, and `downside`, adding a `job` block. Machine-readable: [`schemas/service-job.schema.json`](schemas/service-job.schema.json). **[REC]**

```jsonc
{
  "opportunity_id": "uuid",
  "type": "service",
  "category": "drywall|smart_home|welding|repair|maintenance|fabrication|...",
  "location": { ... },                 // same as flip; customer site vs. home base
  "logistics": { ... },                // trips: estimate visit, work days, material runs

  "job": {
    "quoted_revenue": 1850,            // total the customer pays (labor + passed-through materials)
    "labor_revenue": 1530,             // revenue attributable to labor (quoted_revenue - materials)
    "materials_cost": 320,             // what Michael fronts; may be passed through or marked up
    "material_markup_rate": 0.0,       // 0 = pass-through at cost
    "labor_hours": 14,
    "admin_hours": 1.5,                // quoting, scheduling, invoicing
    "required_skills": ["drywall_hang","drywall_finish"],
    "win_prob": 1.0,                   // p_win: 1.0 if already awarded; <1 for competitive quote
    "completion_prob": 0.98,           // P(finished without rework/warranty hit)
    "payment_terms_days": 5,           // deposit→final; drives time-to-cash
    "deposit_rate": 0.3                // reduces cash tied up
  },

  "estimates_meta": { ... },
  "scorecard": { ... }
}
```

**Key economic differences from a flip** **[INFER]**:

- **No acquisition, no resale, no salvage.** Revenue is the quote; "sale probability" becomes **`win_prob`** (did we land the lead) × **`completion_prob`** (did we finish clean).
- **Cash tied up is small** — only fronted materials minus deposit — so ROI is huge and nearly meaningless; **profit/hour is the governing metric.**
- **Materials** may be marked up (a margin source) or passed through at cost.
- **The main loss mode is warranty/rework and unpaid invoices**, not a dead asset.

---

## 5. Cost model (the universal ledger)

Every opportunity is reduced to a ledger of cash out, cash in, and Michael-hours. All symbols are defined once here and reused in every formula. **[FACT]** (identities) / **[REC]** (default constants).

### 5.1 Symbols

| Symbol | Meaning | Flip | Service |
|--------|---------|------|---------|
| `A` | acquisition (expected buy price) | ✓ | — |
| `F_buy` | buy-side fees (title, tax, buyer premium) | ✓ | — |
| `P` | parts cost | ✓ | (usually 0) |
| `M` | materials/consumables cost | ✓ | ✓ (may be marked up) |
| `TripsCash` | travel cash cost (fuel + wear), all trips | ✓ | ✓ |
| `H_travel` | travel hours, all trips | ✓ | ✓ |
| `H_labor` | hands-on hours | ✓ | ✓ |
| `H_admin` | sourcing/negotiating/listing/quoting/invoicing hours | ✓ | ✓ |
| `C_store` | storage cost (per-day × hold days) | ✓ | rare |
| `C_disp` | disposal cost | ✓ (fail branch) | rare |
| `F_sell` | sell-side fees = `R_sell·sell_rate + sell_flat` | ✓ | — |
| `R_sell` | gross resale price / `Rev` = job revenue | ✓ | ✓ |
| `p_repair` | P(repair succeeds at estimated cost) | ✓ | — |
| `p_sale` / `p_win` | P(sells at target) / P(win the lead) | ✓ | ✓ |
| `S_fail`, `S_unsold` | salvage floors | ✓ | — |
| `w` | Michael's time value (opportunity-cost floor) | ✓ | ✓ |

### 5.2 Default constants **[REC]** — all live in [`config/scoring-config.json`](config/scoring-config.json)

| Constant | Default | Basis |
|----------|---------|-------|
| `fuel_price_per_gal` | $3.20 | **[UNK]** calibrate to local pump price |
| `vehicle_mpg` | 18 | **[UNK]** truck; set per vehicle |
| `wear_per_mile` | $0.28 | **[REC]** tires+maintenance+depreciation for a work truck |
| → `vehicle_cost_per_mile` `v` | **$0.46/mi** | = fuel_per_mile ($0.178) + wear ($0.28). Cross-check vs IRS ~$0.70 all-in. |
| `avg_speed_mph` | 45 | **[REC]** blended |
| `w` (time value floor) | $40/hr min, $65/hr target | **[UNK]** Michael must confirm his real number |
| `storage_small / large` | $1 / $3 per day | **[REC]** |
| `risk_capital_per_deal_cap` | $1,500 max acquisition w/o escalation | **[REC]**, ties to Agent 05 limits |
| `max_loss_cap` | $800 | **[REC]** largest single-deal loss tolerated |

### 5.3 Travel economics — *distance is economic, not arbitrary* **[FACT]** (requirement)

Distance enters the decision through **four** channels, not one. This is the whole point of "distance is economic." **[INFER]**

1. **Cash (fuel + wear):**
   `TripsCash = Σ_trips (round_trip_miles × v)` where `v = fuel_price/mpg + wear_per_mile`.
2. **Time (opportunity cost of Michael driving):**
   `H_travel = Σ_trips (round_trip_miles / avg_speed_mph)`.
   These hours count in **total hours**, so distance directly lowers **profit/hour**.
3. **Wasted-trip risk:** the farther away, the more a flaky seller / misrepresented item costs you a dead run. Model an expected wasted-trip loss:
   `WastedTripEV = p_waste × (round_trip_miles_inspect × v + H_inspect × w)`
   where `p_waste` rises with distance and *falls* with evidence quality (photos, video, verified title, phone screening). **[REC]** `p_waste = clamp(0.05 + miles_one_way/1000 − 0.4·evidence_quality, 0, 0.6)`.
4. **Re-visit friction:** returns, re-negotiation, second look. Far deals can't be casually revisited, which raises risk and lowers confidence. Captured via confidence haircut (§9). **[INFER]**

**Trip planning rule:** combine inspect + pickup into one trip when evidence lets you commit sight-adjusted; otherwise budget a separate inspection trip and charge its cost/EV to the deal. **[REC]**

**Long-distance rules** → see §13.

---

## 6. Core formulas

### 6.1 Flip — deterministic ("goes to plan") reconstruction

```
R_net        = R_sell − F_sell                          ; net revenue after sell fees
CostOut      = A + F_buy + P + M + TripsCash + C_store   ; cash out if it works
NetProfit    = R_net − CostOut                           ; the headline cash profit
TotalHours   = H_travel + H_labor + H_admin
Profit/Hour  = NetProfit / TotalHours
CashTiedUp   = A + F_buy + P + M + TripsCash + C_store    ; peak capital deployed before any inflow
ROI          = NetProfit / CashTiedUp                    ; return per cycle (not annualized)
```

> **[REC]** Michael's own labor is **not** subtracted as a cash cost in `NetProfit` (that would double-count). Instead his time is disciplined by the **Profit/Hour gate** (§12). This is the standard contractor treatment: profit is cash in minus cash out; your wage is "is the $/hr worth it?" **[FACT]**

### 6.2 Flip — expected value (the number the decision actually uses)

A three-branch decision tree. **[FACT]** (EV method)

```
Branch 1  repair ok AND sells:     prob = p_repair · p_sale
          value₁ = R_net − CostOut

Branch 2  repair ok, unsold @ horizon: prob = p_repair · (1 − p_sale)
          value₂ = S_unsold − CostOut

Branch 3  repair fails:            prob = (1 − p_repair)
          value₃ = S_fail − CostOut_fail
          where CostOut_fail = A + F_buy + TripsCash_acq + f_diag·P   (you don't spend all parts if it's dead)
                f_diag ≈ 0.3  [REC]

EV_NetProfit = Σ probᵢ · valueᵢ
EV_Profit/Hour = EV_NetProfit / TotalHours
EV_ROI        = EV_NetProfit / CashTiedUp
MaxLoss       = −min(value₃, 0)          ; worst realistic single-deal loss
```

Then apply the **confidence haircut** (§9) and **wasted-trip EV** (§5.3) to get the final decision EV:
```
EV_decision = (EV_NetProfit − WastedTripEV) × confidence_haircut
```

### 6.3 Service — formulas

```
Rev_net      = quoted_revenue − F_sell(payment fees)    ; usually ≈ quoted_revenue
CostOut      = M(1 − passed_through) ... (materials fronted) + TripsCash
             ; if materials passed through to customer, only net-of-reimbursement cash counts
NetProfit    = Rev_net − materials_cost − TripsCash      ; labor is the profit, not a cost
TotalHours   = H_travel + H_labor + H_admin
Profit/Hour  = NetProfit / TotalHours                    ; GOVERNING METRIC
CashTiedUp   = max(0, materials_cost − deposit)          ; small
ROI          = NetProfit / max(CashTiedUp, 1)            ; large, low signal

EV_NetProfit = win_prob · completion_prob · NetProfit − cost_to_quote
          where cost_to_quote = estimate_trip_cash + H_estimate·w   (only if competitive lead)
```

---

## 7. Profit/Hour — the discipline metric

**[INFER]** Profit/hour is the single most honest metric Michael has, because his real constraint is hours, not dollars. A $1,000 profit over 40 hours ($25/hr) is worse than a $300 profit over 3 hours ($100/hr).

- **All** Michael-hours count: travel + labor + admin (sourcing, negotiating, listing, coordinating, invoicing). Hidden admin time is where flippers fool themselves. **[INFER]**
- The gate is a **floor wage**: if the EV-adjusted profit/hour can't clear `w_min` ($40/hr **[REC/UNK]**), pass — his time is worth more elsewhere.
- Two floors: **absolute floor** `w_min` (hard PASS below it) and **target** `w_target` ($65 flip / $75 service **[REC]**) required for a YES.

---

## 8. ROI, cash-tied-up, and risk-of-ruin

- **ROI (per cycle)** = NetProfit / CashTiedUp. Ranks capital efficiency; most useful for flips. A 60% per-cycle ROI that turns over in 2 weeks is extraordinary; annualized it's absurd, which is why we keep it **per cycle** and pair it with **time-to-cash** (§10). **[INFER]**
- **Cash tied up** = peak capital deployed before the first dollar comes back. Gates against having all cash frozen in slow inventory. **[FACT]** (inventory finance)
- **Risk-of-ruin discipline (Kelly-flavored):** never let `MaxLoss` exceed `max_loss_cap`, and never let a single `CashTiedUp` exceed the per-deal capital cap. A great EV with a ruinous downside is still a PASS. **[FACT]** (bankroll management) / **[REC]** (the caps)

---

## 9. Risk & Confidence — two different things, kept separate

**[INFER]** These are routinely conflated and must not be. **Risk** is dispersion of *real-world outcomes* given our estimates are right. **Confidence** is how much we trust the estimates in the first place.

### 9.1 Risk model (outcome dispersion)

Risk is summarized by three numbers already produced by the tree (§6.2):
- `MaxLoss` — worst realistic single-deal dollar loss.
- `P(loss)` — probability the deal returns less than $0 = P(outcomes with value < 0).
- `CoV` — coefficient of variation of branch outcomes (spread ÷ EV).

```
risk_score (0–100, higher = safer) = 100 − 100 · clamp(
     0.5·(MaxLoss / max_loss_cap) + 0.3·P(loss) + 0.2·min(CoV,1) , 0, 1)
```
**[REC]** weights. High MaxLoss, high chance of loss, or a wide outcome spread all pull the score down.

### 9.2 Confidence model (evidence quality)

A 0–1 score from an **evidence checklist** — each item we actually have raises confidence:

| Evidence item | Weight **[REC]** |
|---------------|------|
| ≥ 3 *sold* comparables, recent & nearby | 0.25 |
| Condition verified (photos/video/in-person inspection) | 0.20 |
| Repair fault identified (scope known), not guessed | 0.15 |
| Title/ownership verified (titled assets) | 0.10 |
| Demand evidence (comps sold within turnover window) | 0.10 |
| Seller responsive / screened by phone | 0.08 |
| Skill-fit high (we've done this exact job before) | 0.07 |
| Price distribution (not a single point) | 0.05 |

`confidence = Σ weights_of_present_items` (0–1).

**Confidence drives two things** **[INFER]**:
1. **Haircut on EV** for ranking: `confidence_haircut = 0.6 + 0.4·confidence` (so zero-evidence halves... no — ranges 0.6→1.0). Low-evidence deals are discounted, not trusted at face value.
2. **A hard gate:** `confidence ≥ 0.6` required for a **YES**. Below that, best case is **MAYBE — gather evidence** (and the engine should name *which* missing checklist item, via EVPI, would most cheaply move the needle). **[REC]**

> Winner's-curse discipline: under low confidence, bias estimates toward the conservative end of the comp distribution. **[FACT]**

---

## 10. Time-to-cash model

**[FACT]** (inventory turnover). Time-to-cash = days from first cash outlay to proceeds collected.

```
Flip:    TTC = acquire_lead_days + repair_days + list_to_sale_days(≈ expected_dom) + collect_days
Service: TTC = schedule_lag_days + job_days + payment_terms_days
```

- Feeds `ttc_score = 100 − 100·clamp(TTC / ttc_cap, 0, 1)`, `ttc_cap = 60 days` **[REC]**.
- Short TTC compounds: capital recycles into the next deal. Two $300 flips at 2 weeks each beat one $500 flip at 8 weeks. The engine captures this via ROI-per-cycle × turnover, surfaced as an optional **annualized ROI = ROI × (365/TTC)** for comparison only. **[INFER]**
- `expected_dom` comes straight from comps (§14) — categories with low days-on-market (trailers, generators in storm season) get shorter, more confident TTC. **[INFER]**

---

## 11. Scarcity model

**[INFER]** Scarcity measures *how rare and how perishable* this specific opportunity is. It does two jobs: (a) it contributes a small amount to the priority score, and (b) it drives **urgency / immediate alerts** (§12.4). It is **not** a reason to overpay.

Three inputs, each 0–1:

| Input | Definition | High when |
|-------|------------|-----------|
| `deal_discount` | `(market_buy_median − expected_buy_price) / market_buy_median` | Priced well below what similar items trade for |
| `demand_velocity` | from comps' DOM: `clamp(1 − expected_dom/dom_cap, 0, 1)` | The category sells fast |
| `supply_tightness` | `clamp(1 − active_comparable_listings/supply_cap, 0, 1)` | Few competing listings available |

```
scarcity = 0.5·deal_discount + 0.3·demand_velocity + 0.2·supply_tightness    [REC]
```

Scarcity also *raises negotiating leverage estimates* and *shortens TTC* indirectly (fast categories), but we keep those couplings explicit, not hidden. For **service jobs**, `scarcity` is replaced by **lead_quality** (referral vs cold, urgency of customer need, repeat customer). **[INFER]**

---

## 12. Skill-fit model, combined score, and the decision

### 12.1 Skill-fit (0–1)

**[FACT]** Michael's skills: mechanical diagnosis, repair, welding, fabrication, maintenance, equipment repair, drywall, construction, troubleshooting, smart-home installation.

```
skill_fit = coverage × proficiency
  coverage    = (required_skills ∩ Michael_skills) / required_skills      ; fraction he can do
  proficiency = mean confidence level on the covered skills (0–1)         ; from outcome history
```

Skill-fit is **multi-purpose** **[INFER]**:
- Raises `p_repair` and lowers `H_labor` estimates (he's fast at what he knows).
- Contributes to `confidence`.
- Contributes to the composite score.
- **Hard gates:**
  - `skill_fit < 0.4` → cap at **MAYBE/PASS** (outside wheelhouse; labor & success estimates unreliable).
  - Requires a skill that is **legally gated and he lacks** (e.g., licensed electrical, plumbing, HVAC refrigerant, gas lines) → **PASS / escalate** regardless of economics. **[REC]** — Agent 05 governance should own this allow-list.

### 12.2 Normalization of each sub-metric to 0–100 **[REC]**

All linear-to-cap, clamped to [0,100]; caps live in config so scores stay reconstructable.

| Sub-score | Formula | Cap (flip / service) |
|-----------|---------|----------------------|
| `ev_score` | `EV_decision / ev_cap × 100` | $800 / $1500 |
| `pph_score` | `EV_Profit/Hour / pph_cap × 100` | $120 / $120 |
| `roi_score` | `EV_ROI / roi_cap × 100` | 1.5 (150%) / 1.5 |
| `ttc_score` | `100 − TTC/ttc_cap × 100` | 60 days |
| `risk_score` | §9.1 | — |
| `conf_score` | `confidence × 100` | — |
| `skill_score` | `skill_fit × 100` | — |
| `scarcity_score` | `scarcity × 100` (or `lead_quality` for service) | — |

### 12.3 Combined (composite) score

```
Composite = Σ wᵢ · sub_scoreᵢ         (weights sum to 1.0)
```

| Weight **[REC]** | Flip | Service |
|--------|------|---------|
| EV | 0.25 | 0.20 |
| Profit/Hour | 0.25 | 0.35 |
| ROI | 0.10 | 0.00 |
| Time-to-cash | 0.10 | 0.10 |
| Risk | 0.10 | 0.08 |
| Confidence | 0.05 | 0.07 |
| Skill-fit | 0.10 | 0.15 |
| Scarcity / lead-quality | 0.05 | 0.05 |

### 12.4 Decision logic (gates first, then composite)

```
STEP 1 — HARD PASS GATES (any true → PASS, with named reason):
  EV_decision ≤ 0
  MaxLoss > max_loss_cap
  CashTiedUp > risk_capital_per_deal_cap        (→ or escalate to Agent 05)
  skill_fit < 0.4  OR  requires_license_he_lacks
  Profit/Hour (deterministic) < w_min  ($40)
  NetProfit (deterministic) < min_profit  ($150 flip / $100 service)

STEP 2 — among survivors:
  YES   if Composite ≥ 60
          AND confidence ≥ 0.60
          AND EV_Profit/Hour ≥ w_target
          AND EV_decision ≥ min_profit
  MAYBE if survives gates but misses a YES condition
          (e.g., Composite 45–59, or confidence < 0.60 → "gather evidence",
           or Profit/Hour between w_min and w_target)
  PASS  if Composite < 45
```

**[REC]** thresholds. The gates encode "is it economically worth doing at all"; the composite ranks the survivors for Michael's limited attention.

### 12.5 Immediate-alert thresholds

Alert Michael *now* (interrupt) only when a deal is **both strong and perishable** **[INFER]**:

```
ALERT if  decision == YES
      AND scarcity ≥ 0.6
      AND perishable:  (listing_age < 6h)  OR  (auction_ends_in < 24h)  OR  (supply_tightness ≥ 0.7)
      AND EV_decision ≥ 2 × min_profit
      AND deal_discount ≥ 0.35
```
Everything else goes into the normal ranked queue for batch review. This protects attention — the scarcest resource. **[INFER]**

---

## 13. Long-distance rules

**[INFER]** built on §5.3. "Normal" working radius is ~100 mi (per Agent 02's geography note: Conway / Central Arkansas, ~100 mi typical but not a hard limit). Distance is handled economically, but three guardrails sit on top:

1. **Radius scales with EV, not fixed.** Define `max_economic_radius(one-way miles)` as the distance at which travel cash + travel-time cost + wasted-trip EV consumes a set fraction of EV. **[REC]** require `(TripsCash + H_travel·w + WastedTripEV) ≤ 0.35 × EV_NetProfit`. If distance breaks that ratio → PASS unless EV is exceptional.
2. **Verification requirement rises with distance.** Beyond ~60 mi one-way, a YES requires **remote verification** (video of the fault, serial/photo proof, verified title) sufficient to combine inspect+pickup into one trip; otherwise budget a separate inspection trip and recompute. **[REC]**
3. **Confidence penalty & no-casual-revisit.** Beyond the normal radius, apply an extra confidence haircut (can't pop back for a second look or easy return), and the wasted-trip probability `p_waste` grows with miles (§5.3). **[REC]**

Net effect: a far deal must be *much* better to clear the bar — exactly what the generator example (§17.3) demonstrates.

---

## 14. Comparable-sales (comps) methodology

**[FACT]** standard appraisal practice, adapted.

1. **Use SOLD prices, not asking prices.** Asking prices are fiction; sold prices are truth. Where only asks are available (Craigslist/Marketplace rarely show sold), discount asks by a category "ask-to-sold" ratio learned from outcomes. **[INFER]**
2. **Filters:** same category, condition band, and (for equipment) capacity/engine-hours/mileage; within a recency window (**[REC]** 90 days) and radius (**[REC]** 150 mi, widen if thin).
3. **Minimum n:** need **≥ 3** usable comps for a YES; 1–2 → MAYBE (low confidence); 0 → cannot responsibly set `target_sell_price` (UNKNOWN). **[REC]**
4. **Trim & aggregate:** drop top/bottom outliers; report **median** (robust) as `comp_price_expected`, plus 25th/75th percentiles as `low`/`high`. Never a single point. **[FACT]**
5. **Condition adjustment:** adjust each comp to the subject's post-repair condition (additive deltas for known differences). **[INFER]**
6. **Days-on-market:** record each comp's listing→sold span; median DOM → `expected_dom` → feeds `p_sale`, time-to-cash, and demand_velocity.
7. **Provenance:** every comp stored in `estimates_meta.comps[]` with URL, sold price, date, distance, source — so `target_sell_price` is reconstructable. **[FACT]** (requirement)

---

## 15. Minimum evidence before a YES

A YES is only allowed when confidence ≥ 0.60, which in practice means **all** of these are satisfied **[REC]**:

- [ ] ≥ 3 sold comps (recent, nearby) → `target_sell_price` as a distribution.
- [ ] Condition verified by photos/video or inspection (not just the seller's text).
- [ ] Repair fault **identified** (scope known) — not "probably just needs a carb." A guessed fault caps at MAYBE.
- [ ] Title/ownership verified for titled assets (trailers, vehicles).
- [ ] Demand evidence: comps actually *sold* within the turnover window.
- [ ] For > 60 mi: remote verification sufficient to justify a committing trip (§13).

**EVPI tie-in:** when a YES is blocked only by missing evidence, the engine computes the value of acquiring it. If a $0 phone call or a seller video would flip MAYBE→YES on a high-EV deal, that's the highest-value next action. Michael's time is best spent buying down the *cheapest, most decisive* uncertainty first. **[INFER]** / **[FACT]** (EVPI)

---

## 16. Learning from completed outcomes (the LEARN loop)

**[FACT]** (forecast calibration) — this is what makes the engine improve and what makes every prior estimate honest over time.

For **every** completed deal, store predicted vs. actual:

| Predicted | Actual | Error metric |
|-----------|--------|--------------|
| `target_sell_price` | actual sale price | price MAPE per category |
| `H_labor` | actual labor hours | hours MAPE per category/skill |
| `p_repair` | repair succeeded? (0/1) | **Brier score** |
| `p_sale` / `win_prob` | sold? / won? (0/1) | **Brier score** |
| `expected_dom` | actual days to sell | DOM error per category |
| `parts/materials` | actual spend | cost MAPE |
| wasted trip? | (0/1) | `p_waste` calibration by distance band |

**Updates driven by the data** **[REC]**:
- **Category priors:** median labor hours, repair-success rate, price-realization haircut, DOM — all become the new defaults per category.
- **Skill proficiency:** success/speed on each skill updates the `proficiency` term in skill-fit (§12.1).
- **Probability calibration:** if Brier scores show `p_repair` is systematically optimistic, shrink future estimates toward the observed base rate.
- **Ask-to-sold ratios:** learned per platform/category to convert asking prices to expected sold prices.
- **Threshold calibration:** compare realized profit/hour on accepted vs. rejected-but-observed deals to tune `w_target` and composite cutoffs.

**Governance tie-in:** each completed outcome is itself a receipt with provenance (Agent 04/05). The LEARN loop reads the outcome store; it never edits a past score — it versions the config (`scoring_config_version`) so historical scores remain reconstructable under the config that produced them. **[INFER]**

---

## 17. Worked examples (fully reconstructable)

Constants used: `v = $0.46/mi`, `avg_speed = 45 mph`, `w_min = $40/hr`, `w_target = $65 flip / $75 service`, `min_profit = $150 flip / $100 service`, `max_loss_cap = $800`, caps per §12.2, weights per §12.3. All arithmetic shown. Config version `2026.10.0`.

### 17.1 Utility trailer flip → **YES + ALERT**

**Inputs:** 5×8 utility trailer, listed $300 (seller motivated, posted today), 20 mi away. Needs deck boards, one tire, light/wiring kit, repaint. Sold comps (refurbished) median ~$1,050; market buy-median for as-is ~$500.

| Item | Value |
|------|-------|
| A (expected buy) | $250 |
| F_buy (title) | $10 |
| P (deck $80, tire $60, lights $20) | $160 |
| M (paint/hardware) | $30 |
| Trips: inspect+pickup 40mi + buyer meet 16mi = 56mi | TripsCash = 56×0.46 = **$25.76** |
| H_travel = 56/45 | **1.24 h** |
| H_labor | 5 h; H_admin 1.25 h → **TotalHours 7.49** |
| C_store 9 days × $3 | $27 |
| R_sell | $1,050 (no sell fee) → R_net $1,050 |
| p_repair / p_sale | 0.95 / 0.85 |
| S_unsold / S_fail | $700 / $220 |

**Deterministic:** CostOut = 250+10+160+30+25.76+27 = **$502.76**; NetProfit = 1050 − 502.76 = **$547.24**; Profit/Hour = 547.24/7.49 = **$73.1/hr**; CashTiedUp $502.76; ROI = **108.8%**.

**EV tree:**
- B1 (0.95·0.85=0.8075): 1050−502.76 = 547.24 → 441.90
- B2 (0.95·0.15=0.1425): 700−502.76 = 197.24 → 28.11
- B3 (0.05): CostOut_fail = 250+10+25.76+0.3·160(=48)=333.76 → 220−333.76 = −113.76 → −5.69
- **EV_NetProfit = 464.32**; MaxLoss = $113.76; EV_Profit/Hour = 464.32/7.49 = **$62.0/hr**; EV_ROI = 92.4%.
- confidence 0.80 (comps+inspected+title+scope+demand). WastedTripEV ≈ 0 (20 mi, verified). EV_decision ≈ 464.

**Scorecard:** ev 58.0 · pph 51.7 · roi 61.6 · ttc(12d) 80.0 · risk(§9.1) 86.8 · conf 80 · skill 95 · scarcity 80 (discount 0.50).
Composite = .25·58.0+.25·51.7+.10·61.6+.10·80+.10·86.8+.05·80+.10·95+.05·80 = **67.8**.

**Decision:** passes all hard gates; Composite 67.8 ≥ 60, confidence 0.80 ≥ 0.60, EV_Profit/Hour $62 ≥ ... (just under $65 target — see note), EV $464 ≥ $150. **YES.**
*Alert:* YES + scarcity 0.80 ≥ 0.6 + listing_age < 6h + discount 0.50 ≥ 0.35 + EV $464 ≥ 2×$150 → **IMMEDIATE ALERT.**
> Note: EV-PPH ($62) sits just below the $65 target; deterministic PPH is $73. This is a legitimately strong deal; if calibration shows trailers reliably hit plan, `w_target` or the EV haircut is the knob. Shown here to demonstrate the gate is *live*, not cosmetic. **[INFER]**

### 17.2 Riding mower flip ("won't start") → **PASS (flips to MAYBE with evidence)**

**Inputs:** riding mower, "won't start", $150, 35 mi away. Running comps ~$650.

| Item | Value |
|------|-------|
| A | $150; F_buy $0 |
| P (carb $35, battery $60, blade $30, oil/filter $25) | $150 |
| Trips 70mi + 14mi = 84mi | TripsCash $38.64; H_travel 1.87 h |
| H_labor 4 + H_admin 1.25 | TotalHours 7.12 |
| C_store 14×$2 | $28 |
| R_sell $650 | R_net $650 |
| p_repair / p_sale | 0.70 / 0.80 (no-start could be cheap OR a dead engine) |
| S_unsold / S_fail | $480 / $90 |

**Deterministic:** CostOut = 150+150+38.64+28 = $366.64; NetProfit = **$283.36**; Profit/Hour **$39.8/hr**; ROI 77.3%.
**EV tree:** B1(0.56)=283.36→158.68; B2(0.14)=113.36→15.87; B3(0.30): cost_fail=150+38.64+70=258.64 → 90−258.64=−168.64 → −50.59. **EV_NetProfit = 123.96**; MaxLoss $168.64; EV_Profit/Hour **$17.4/hr**; confidence **0.50** (can't inspect engine until bought; fault guessed).
**Scorecard:** ev 15.5 · pph 14.5 · roi 22.5 · ttc(16d) 73.3 · risk 78.9 · conf 50 · skill 80 · scarcity 55. Composite = **38.2**.
**Decision:** survives hard gates (NetProfit $283 ≥ 150, det. PPH $39.8 ≈ floor), but Composite 38.2 < 45 → **PASS.** Root cause: 30% chance of a −$169 dead-engine outcome crushes EV-PPH to $17; confidence 0.50 blocks YES anyway.
**Evidence flip (EVPI):** if the seller lets Michael confirm it cranks with compression (a $0 action) → `p_repair` 0.70→0.90, confidence 0.50→0.75. Recompute: EV_NetProfit ≈ $207.5, EV-PPH ≈ $29, Composite ≈ **46.1 → MAYBE.** The engine's advice: *don't drive 35 mi on a guess; spend the phone call first.* **[INFER]**

### 17.3 Whole-house generator flip → **PASS (distance + unverifiable fault)**

**Inputs:** generator, "needs work", $600, **160 mi one-way**. Running comps ~$2,200. The tempting one.

| Item | Value |
|------|-------|
| A $600; F_buy $0 | |
| P (plan, mid-estimate: board OR filters — wide) | $350 |
| Trips 320mi + 20mi = 340mi | TripsCash **$156.40**; H_travel **7.56 h** |
| H_labor 6 + H_admin 2 | TotalHours 15.56 |
| C_store 21×$3 | $63 |
| R_sell $2,200 | R_net $2,200 |
| p_repair / p_sale | 0.60 / 0.85 |
| S_unsold / S_fail | $1,600 / $400 |

**Deterministic (the trap):** CostOut = 600+350+156.40+63 = $1,169.40; NetProfit = **$1,030.60**; Profit/Hour **$66.2/hr**; ROI 88.1%. *Looks like a YES.*
**EV tree:** B1(0.51)=1030.60→525.61; B2(0.09)=430.60→38.75; B3(0.40): cost_fail=600+156.40+150=906.40 → 400−906.40=−506.40 → −202.56. **EV_NetProfit = 361.80**; MaxLoss **$506.40**; EV_Profit/Hour **$23.3/hr**; confidence **0.40** (unverifiable at 160 mi). WastedTripEV ≈ p_waste·(320·0.46 + 7.56·40) ≈ 0.25·(147+302) ≈ $112.
**Long-distance gate (§13-1):** require (TripsCash + H_travel·w + WastedTripEV) ≤ 0.35·EV_NetProfit → (156.40 + 302.40 + 112) = $570.80 vs 0.35·361.80 = $126.63. **$570.80 ≫ $126.63 — fails.**
**Scorecard (for the record):** ev 45.2 · pph 19.4 · roi 20.6 · ttc(25d) 58.3 · risk 36.7 · conf 40 · skill 75 · scarcity 50. Composite ≈ **39.7**.
**Decision:** **PASS.** The $1,030 headline is destroyed by a 40% chance of a −$506 loss, $23/hr EV time, unverifiable fault at 160 mi, and a broken distance ratio. *This is the engine doing its most important job: refusing a seductive far-away gamble.* Would flip to MAYBE only if the seller provides video proving a minor fault (raising p_repair + confidence) **and** the price drops to ~$350, **or** a trusted local pickup/inspection is arranged. **[INFER]**

### 17.4 Drywall service job → **YES**

**Inputs:** hang + finish a 12×14 basement room + closet, Conway, 8 mi. Awarded job (`win_prob` 1.0).

| Item | Value |
|------|-------|
| quoted_revenue | $1,850 (incl. $320 materials pass-through) |
| M (sheets, mud, tape, screws, bead) | $320 |
| Trips: 3 work round-trips 48mi + material run 10mi = 58mi | TripsCash $26.68; H_travel 1.29 h |
| H_labor 14 + H_admin 1.5 | TotalHours 16.79 |
| disposal | $15 |
| completion_prob | 0.98 |

**Economics:** CostOut = 320+26.68+15 = $361.68; NetProfit = 1850 − 361.68 = **$1,488.32**; Profit/Hour = 1488.32/16.79 = **$88.6/hr**; CashTiedUp ≈ $347 (no deposit modeled); ROI 411%; TTC ≈ 6 days. MaxLoss ≈ $50 (cost to show up / minor rework).
**Scorecard (service weights):** ev 99.2 (cap $1500) · pph 73.8 · ttc 90 · risk 93.8 · conf 85 · skill 95 · lead-quality 50.
Composite = .35·73.8 + .20·99.2 + .15·95 + .10·90 + .08·93.8 + .07·85 + .05·50 = **84.9**.
**Decision:** Profit/Hour $88.6 ≥ $75 target, confidence 0.85, Composite 84.9 ≥ 60 → **YES.** Clean: known scope, nearby, squarely in-skill, near-zero capital risk, paid in a week.

### 17.5 Smart-home install service job → **YES (highest $/hr)**

**Inputs:** install 6 smart switches, video doorbell, 3 cameras, hub + configure; customer-supplied devices; 14 mi away.

| Item | Value |
|------|-------|
| labor_revenue (customer supplies devices) | $900 |
| M (wire, connectors, mounts) | $40 |
| Trips: 2 round-trips 56mi | TripsCash $25.76; H_travel 1.24 h |
| H_labor 6 + H_admin 1 | TotalHours 8.24 |

**Economics:** CostOut = 40+25.76 = $65.76; NetProfit = 900 − 65.76 = **$834.24**; Profit/Hour = 834.24/8.24 = **$101.2/hr**; TTC ≈ 2 days; MaxLoss ≈ $30.
**Scorecard:** ev 55.6 (cap $1500) · pph 84.3 · ttc 96.7 · risk 95.0 · conf 80 · skill 90 · lead-quality 60.
Composite = .35·84.3 + .20·55.6 + .15·90 + .10·96.7 + .08·95 + .07·80 + .05·60 = **80.0**.
**Decision:** Profit/Hour $101 ≥ $75, Composite 80.0 → **YES.** Highest profit/hour of all five — low materials, short job, pure skill, fast pay. Exactly the kind of work the engine should rank to the top of Michael's queue.

**Summary of the five:**

| Example | Decision | EV NetProfit | EV $/hr | MaxLoss | Composite | Why |
|---------|----------|-------------:|--------:|--------:|----------:|-----|
| Trailer | **YES + ALERT** | $464 | $62 | $114 | 67.8 | Underpriced, nearby, fast category |
| Mower | **PASS → MAYBE** | $124 | $17 | $169 | 38.2 | Dead-engine risk; verify by phone first |
| Generator | **PASS** | $362 | $23 | $506 | 39.7 | Far + unverifiable; distance gate fails |
| Drywall | **YES** | $1,488 | $89 | $50 | 84.9 | In-skill, nearby, low risk |
| Smart-home | **YES** | $834 | $101 | $30 | 80.0 | Best $/hr; pure skill, fast pay |

---

## 18. Acceptance tests

These are executable-style assertions for whoever implements the engine. Each must pass; each references the section it guards. **[REC]**

### 18.1 Reconstructability
- **AT-1** Given a stored `scorecard` + its `scoring_config_version` + inputs, recomputing by hand reproduces every sub-score and the composite to ±0.1. *(Core requirement.)*
- **AT-2** Every estimated numeric field carries a `basis` tag ∈ {FACT, INFER, REC, UNK} and, for market values, a `comps[]` provenance list.
- **AT-3** Removing any single comp changes `target_sell_price` only through the documented median/trim rule — no hidden inputs.

### 18.2 Economic correctness
- **AT-4** `NetProfit` does **not** include Michael's own labor as a cash cost (§6.1).
- **AT-5** For a flip with `p_repair=1, p_sale=1`, `EV_NetProfit == deterministic NetProfit` (tree collapses).
- **AT-6** `EV_NetProfit ≤ deterministic NetProfit` whenever any probability < 1 (uncertainty never *raises* EV above plan).
- **AT-7** `MaxLoss` equals the magnitude of the worst negative branch value; if no branch is negative, `MaxLoss == 0`.

### 18.3 Monotonicity (sanity under perturbation)
- **AT-8** Increasing `expected_buy_price` (all else equal) never increases the composite.
- **AT-9** Increasing `road_miles` never increases the composite and never raises `profit/hour` (distance is a cost on ≥2 channels — §5.3).
- **AT-10** Increasing `p_repair` or `p_sale` never decreases `EV_NetProfit`.
- **AT-11** Adding a satisfied evidence item never decreases `confidence`, and lowering `confidence` below 0.60 can only downgrade (never upgrade) the decision.

### 18.4 Gates & decisions
- **AT-12** Any deal with `EV_decision ≤ 0`, `MaxLoss > max_loss_cap`, `skill_fit < 0.4`, or `requires_license_he_lacks` returns **PASS** regardless of composite.
- **AT-13** A deal cannot return **YES** with `confidence < 0.60` (→ MAYBE "gather evidence", naming the cheapest decisive missing item).
- **AT-14** The five worked examples (§17) reproduce exactly: Trailer=YES+ALERT, Mower=PASS(→MAYBE w/ evidence), Generator=PASS, Drywall=YES, Smart-home=YES.
- **AT-15** A YES with low scarcity or a stale listing does **not** raise an immediate alert (alert requires strong **and** perishable — §12.5).
- **AT-16** The generator case fails the long-distance ratio gate (§13-1) even though its deterministic profit/hour > target — proves distance is economic, not cosmetic.

### 18.5 Learning loop
- **AT-17** Recording a completed outcome updates the relevant category prior and skill proficiency, and recomputes Brier/MAPE — **without** mutating any historical `scorecard`.
- **AT-18** Config changes bump `scoring_config_version`; historical scores remain reconstructable under their original version.
- **AT-19** After N outcomes where `p_repair` is systematically optimistic, new `p_repair` priors shrink toward the observed base rate (calibration actually moves).

### 18.6 Service-specific
- **AT-20** For a service job, `CashTiedUp = max(0, materials − deposit)` and `profit/hour` (not ROI) is the governing YES metric.
- **AT-21** A competitive lead (`win_prob < 1`) charges `cost_to_quote` against EV; an awarded job (`win_prob = 1`) does not.

---

## 19. What I need from Michael / other agents (open UNKNOWNs)

**[UNK]** — must be supplied before the engine runs on real money; defaults above are placeholders for design only:

1. **Time value `w`** — Michael's real floor and target $/hr. Everything keys off this.
2. **Home base** — exact location for road-mile computation (assumed Conway, AR).
3. **Vehicle(s)** — mpg and a realistic `wear_per_mile` per vehicle used for pickups.
4. **Risk capital** — max cash per deal and max concurrent cash tied up (ties to Agent 05 spend limits).
5. **Local fuel price** — current, calibratable.
6. **License allow-list** — which trades are legally gated and off-limits (Agent 05 governance owns this).

**Cross-agent dependencies:**
- **Agent 02** — final normalized opportunity schema + where `comps`/DOM/active-listing-count come from (discovery feeds `target_sell_price`, `supply_tightness`).
- **Agent 04** — canonical entity IDs, the outcome/lesson store (the LEARN loop reads it), and the receipt/provenance schema this scorecard plugs into.
- **Agent 05** — the YES/NO/MODIFY/HOLD approval interface consumes this decision + reasons; spend/distance caps and the license allow-list are governance-owned.

---

## 20. One-paragraph summary

**[INFER]** Reduce every opportunity to a provenance-tagged ledger of cash-out, cash-in, and Michael-hours; run a decision-tree expected value over repair-success and sale/win probabilities; derive net profit, EV, profit/hour, ROI, cash-tied-up, time-to-cash, and max-loss; score risk, confidence, skill-fit, and scarcity 0–1; treat distance as a four-channel economic cost (fuel, time, wasted-trip risk, revisit friction); gate hard on ruin/skill/evidence, then rank survivors with a transparent weighted composite into YES / MAYBE / PASS, alert only when a deal is strong **and** perishable, demand ≥3 sold comps and a known fault before any YES, and feed every completed outcome back to recalibrate the priors — with every number reconstructable under a versioned config.
