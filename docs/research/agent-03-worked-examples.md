# Agent 03: Round-Two Worked Examples (engine v0.1.0, config 2026.10.1)

Every number below is engine output, and every one is also checked:
- by an independent float reference ledger, to the cent (`economics/tests/helpers.py`)
- by the literal assertions in `economics/tests/test_worked_*.py`

The full scorecards are in `economics/examples/*.scored.json`. Each file is an Item v1 with `scores`, a `recommendation`, a provenance record and receipt drafts, and each replays byte-for-byte. All inputs are illustrative; none of them is a real listing.

Constants (config 2026.10.1):
- vehicle cost v = 3.20/18 + 0.28 = **$0.4578/mi**; average speed 45 mph
- **$40/h** floor; **$65** flip target / **$75** service target
- **$1,500** cash cap per deal; **$800** max-loss cap
- min profit $150 flip / $100 service

The dollar figures above are the coordinator's defaults, held in config (not code) until Michael decides them.

## Summary (7 categories, 13 cases)

| Case | Lane | Net (det.) | $/h (det.) | EV net | EV $/h | Max loss | Cash tied | Conf. | TTC d | Composite | Verdict | Walk-away / min quote | Blocking |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|--:|---|
| trailer_utility (§17.1, **C14**) | flip | $547.37 | $73.04 | $464.81 | $62.02 | $106.31 | $502.63 | 0.93 | 10 | 65.49 | **MAYBE** | $227 | ev_pph_target_ok |
| trailer_utility_at_walkaway | flip | $572.37 | $76.37 | $489.81 | $65.36 | $81.31 | $477.63 | 0.93 | 10 | 67.93 | **YES + ALERT** | $227 | |
| mower_no_start (§17.2) | flip | $283.54 | $39.84 | $133.56 | $18.77 | $137.05 | $366.46 | 0.57 | 15 | 37.47 | **PASS** | none | pph_floor_ok |
| mower_compression_confirmed | flip | $283.54 | $39.84 | $210.88 | $29.63 | $137.05 | $366.46 | 1.00 | 15 | 47.77 | **PASS** | none | pph_floor_ok |
| generator_far (§17.3) | flip | $1,031.34 | $66.30 | $384.20 | $24.70 | $451.50 | $1,168.66 | 0.30 | 22 | 36.95 | **PASS** | none | distance_ratio_ok |
| project_vehicle_civic | flip | $1,211.11 | $119.78 | $919.41 | $90.93 | $445.89 | $1,388.89 | 0.93 | 22 | 75.31 | **YES** | $1,061 | |
| project_vehicle_truck_over_cap | flip | $1,826.11 | $180.60 | $1,384.61 | $136.94 | $788.89 | $2,973.89 | 0.93 | 22 | 77.83 | **PASS** | $926 | cash_ok |
| trailer_enclosed_coordinator (01 example) | flip | $644.54 | $65.33 | $443.55 | $44.95 | $455.46 | $1,455.46 | 0.20 | 15 | 43.06 | **PASS** | none | composite < 45 |
| drywall_basement (§17.4) | service | $1,488.46 | $88.66 | $1,469.96 | $87.55 | $0.00 | $361.54 | 0.80 | 11 | 80.07 | **YES** | $1,638 | |
| drywall_patch_coordinator (01 example) | service | $388.04 | $63.96 | $224.83 | $59.44 | $7.32 | $0.00 | 0.15 | 4 | 51.09 | **MAYBE** | none | composite, confidence, ev_pph |
| smart_home_install (§17.5) | service | $834.36 | $101.20 | $820.86 | $99.57 | $0.00 | $65.64 | 0.85 | 5 | 77.55 | **YES + ALERT** | $695 | |
| smart_home_needs_new_circuit | service | $834.36 | $101.20 | $820.86 | $99.57 | $0.00 | $65.64 | 0.85 | 5 | 72.05 | **PASS** | none | license_ok |
| equipment_repair_zero_turn | service | $585.72 | $79.69 | $441.40 | $71.62 | $13.73 | $24.95 | 0.70 | 11 | 60.46 | **MAYBE** | $1,098 | ev_pph_target_ok |

**How to read the walk-away and min-quote column:**
- **Walk-away** (flips) is the highest whole-dollar buy price at which the verdict is still YES. It is the offer ceiling.
- **Min quote** (services) is the lowest whole-dollar quote that scores YES.
- **"none"** means no price makes it YES, because something other than price blocks it.

## A. Trailer, round-one §17.1 inputs: the C14 case, shown in full

**Inputs:**
- buy $250 + $10 title; parts $160; materials $30; labor 5 h; admin 1.25 h
- trips: 40 mi inspect + pickup, 16 mi buyer meet
- storage 9 d × $3
- sale $1,050 (4 sold comps, $950–$1,150), p_sale 0.85; p_repair 0.95
- salvage: $700 if unsold, $220 if the repair fails
- market as-is median $500; listed 2 h ago; 6 competing listings

| Step | Arithmetic | Result |
|---|---|--:|
| Trip cash | 40 × 0.4578 = 18.312 → 18.31; 16 × 0.4578 = 7.3248 → 7.32 | $25.63 |
| Travel h | 40/45 = 0.8889; 16/45 = 0.3556 | 1.2445 h |
| Total h | 1.2445 + 5 + 1.25 | 7.4945 h |
| CostOut = cash tied up | 250 + 10 + 160 + 30 + 25.63 + 27 | $502.63 |
| Net (det.) | 1,050 − 502.63 | $547.37 |
| $/h (det.) | 547.37 / 7.4945 | $73.04 |
| B1 sold | 0.95·0.85 = 0.8075 × 547.37 | 441.9963 |
| B2 unsold | 0.1425 × (700 − 502.63) | 28.1252 |
| B3 failed | fail cost 250 + 10 + 18.31 (pickup trip only) + 0.3·160 = 326.31; 0.05 × (220 − 326.31) | −5.3155 |
| EV net | sum | $464.81 |
| EV $/h | 464.81 / 7.4945 | **$62.02** |
| Confidence | comps .25 + condition .20 + fault .15 + title .10 + demand .10 + seller .08 + price spread .05 (skill fit 0.7667 < 0.85, so that item is not credited) | 0.93 |
| EV after haircut | 464.81 × (0.6 + 0.4·0.93 = 0.972) | $451.80 |
| Sub-scores | ev 451.80/800 = 56.48 · pph 62.02/120 = 51.68 · roi 0.9248/1.5 = 61.65 · ttc 100 − 10/60 = 83.33 · risk 100·(1 − [.5·106.31/800 + .3·.05 + .2·.3849]) = 84.16 · conf 93 · skill 76.67 · scarcity .5·.5 + .3·.8444 + .2·.70 = 64.33 | |
| Composite | .25·56.48 + .25·51.68 + .1·61.65 + .1·83.33 + .1·84.16 + .05·93 + .1·76.67 + .05·64.33 | 65.49 |

**Verdict.** All 8 gates pass and the composite is ≥ 60. But EV $62.02/h < the $65 target, so the verdict is **MAYBE** ("YES blocked: EV profit/hour $62.02 < flip target $65.00").
- The alert does not fire, because an alert requires YES.
- Walk-away is **$227**. At a $225 buy, EV is $65.36/h, which gives **YES + ALERT** (listed 2 h ago, scarcity 0.64, discount 0.55, EV ≥ 2×$150).
- Round one called this case YES. That contradicted its own rule; see ADR-03-002 §1.

## B. Drywall, round-one §17.4 inputs, in full

| Step | Arithmetic | Result |
|---|---|--:|
| Trips | 3 × 16 mi (7.32 each, 0.3556 h each) + 10 mi (4.58, 0.2222 h) | $26.54 / 1.2890 h |
| CostOut | 320 materials + 26.54 + 15 disposal | $361.54 |
| Net (det.) | 1,850 − 361.54 | $1,488.46 |
| $/h | 1,488.46 / (1.289 + 14 + 1.5 = 16.789) | $88.66 |
| Won clean | 1.0 · 0.98 × 1,488.46 | 1,458.6908 |
| Won, goes bad | 0.02 × ([0 deposit + 0.5 × 1,850] − 361.54 = 563.46) | 11.2692 |
| Lost bid | 0 × −0 (awarded job; no quote trip) | 0 |
| EV net | | $1,469.96 |
| EV $/h | 1,469.96 / 16.789 | $87.55 |

Confidence 0.80: scope .30 + customer .15 + written price .15 + materials .10 + access .10. Skill fit is 0.825, below 0.85, so it is not credited.

**YES.** Min quote for YES is $1,638.

## C. What changed against round one, and why
- **Trailer:** YES → MAYBE. C14: the rule was kept and the test corrected.
- **Mower:** "PASS → MAYBE with evidence" → PASS in both variants. Deterministic $39.84/h is below the $40 floor, and evidence cannot fix hours.
- **Generator:** PASS in both rounds. It now fails specifically on the distance ratio gate, even though deterministic $/h ($66.30) beats the target (AT-16).
- **Drywall and smart-home:** YES in both rounds. Composites differ from round one's hand estimates (80.07 vs 84.9; 77.55 vs 80.0). Round one hand-picked the confidence, risk and skill sub-scores; the engine now derives them from inputs and config.
- **Per-mile cost:** $0.4578 instead of $0.46 everywhere (F1).
