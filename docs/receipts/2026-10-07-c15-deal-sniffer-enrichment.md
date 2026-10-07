# Receipt: C-15 (P0), Deal Sniffer enrichment blocks (Agent 03)

- **Date:** 2026-10-07
- **Task:** `C-15` (READY_QUEUE @ agent-01 `d2ef52f`; ADR-0011; from Michael's explicit request for the opportunity card). Claimed at `67f4c68`. Code at `2575ed3` (package 0.9.0, priors 2026.10.4).
- **Scope:** this branch only; DRY-RUN; nothing external contacted.
  - Agent 01's `mbos` package (@ `c4f0156`) was installed `--no-deps` from a read-only archive into the session scratch venv.
  - `config/operator_profile.v1.json` is pinned byte-identical as a test fixture.

## What was built
`mbos_economics.enrich.build_enrichment(item, as_of, cfg=, priors=, seasonality=, profile=, listing_activity=)` is pure and deterministic. It returns `{blocks, provenance, omitted, enrichment_hash}`.
- **`economics`:**
  - `max_acquisition`: the engine's walk-away price when scored YES. Otherwise the **economic ceiling**, the highest price that clears the $/h target and every hard limit, flagged "not a YES yet".
  - `opening_offer`: 70% of a fixed ask, floored to $5 and never above the ceiling.
  - `resale_conservative/likely/optimistic`: percentiles of **FACT sold comps**. The count is stated, trimmed outliers are said so, and 2- and 1-comp cases degrade honestly.
  - `transport_cost`, `days_to_cash` (with a range from the comps' days on market).
- **`logistics`:** `transport_mode`, `trip_miles_round_trip` (pickup trip only), `trip_hours`, `fuel_cost`, `difficulty` (easy / moderate / hard by mode and distance).
- **`seasonality`:** `demand_now`, `hold_likely`, `peak_months`, `note`, from the **sourced** table.
- **`why`:** plain-English reasons from gates and facts. The listing-age sentence is built when Agent 02's `listing_activity` block is supplied. No scorer, placeholder or hash text.

## Transport is an economic input (R19)
- The engine accepts an optional `economics.logistics.transport` input: `mode`, `extra_cash`, `extra_hours`. It adds cash to cost out and hours to total hours.
- **No gate reads it** (tested).
- The numbers are borrowed-trailer penalties in the estimation priors (`transport.penalty`, REC): $20 + $0.14 per pickup mile and 1.0 h. Owned-trailer penalties are smaller.
- Classification happens only where **definite**: zero-turn / riding mower, forklift and UTV need a trailer; push mower, portable generator, MIG welder, tools and towed trailers do not. Everything else is UNKNOWN, with no penalty and a non-blocking `transport_unclassified` gap.
- The card keeps `borrowed_trailer_confirmed` UNKNOWN.

## Seasonality sourcing (FACT about my process)
I ran web searches on 2026-10-07, and each claim comes from a search-result summary; **the pages were not independently read**. Each entry records that.
- **Mower:** Consumer Reports and Bob Vila. Dealers clear riding mowers in early fall and rarely discount May–September. New-unit dealer pricing is used as evidence for used demand **by inference**.
- **Generator:** a Generac SEC S-1/A and a YipitData blog on outage-driven demand. The spring-low months are my inference.
- **Trailer:** a BigRentals guide on rental demand, used by inference for resale.
- **Concrete saw:** no usable data found. The entry rests on Michael's example (via Agent 01) and is marked `RECOMMENDATION`, **to be confirmed**.
- Several search hits were spam mirror sites; they were not used.
- All months are national / Sun-Belt generalizations; Arkansas timing is UNKNOWN.

## Acceptance evidence (FACT)
- **Different seasonality for saw vs mower (goldens `examples/deal_sniffer/*.json`):** in October the mower is `weak` ("long: likely to hold until March") and the saw is `normal` ("typical for the category", no peak months). In April the mower flips to `strong` and the saw stays `normal`.
- **A trailer-requiring deal is scored, not rejected:**
  - The zero-turn mower needs a trailer (+$27, +1 h), and all gates pass.
  - The same deal with the penalty removed scores higher (composite and EV), with identical gates.
  - A 70-mile version is rated `hard` and is still YES/MAYBE with every gate green.
- **`mbos.card.validate_card` is clean** (real card code, Agent 01 @ `c4f0156`) for the mower, saw and trailer. The card shows `borrowed_trailer_confirmed: UNKNOWN`, the saw's transport mode as UNKNOWN listed in `unknowns`, and lane C's `why` lines first.
- **Suite:** 229 passed with all environments (lane-D and card), 223 passed with 6 clean skips by default, and the py3.10 stdlib run is OK.

## Bugs found by my own smoke run and fixed before commit
1. The transport figures never reached `scorecard.derived` (a silent no-op edit), so notes read "$0 and 0 h". Fixed, and tests assert the exact $27 / 1 h.
2. `max_acquisition` was missing on every deal still awaiting evidence, because the engine's walk-away price needs a full YES. Added the economic ceiling.
3. The comps note said "3 FACT sold comps" when 5 were selected and 2 trimmed. It now states both.
4. Smaller fixes: a "(s)" count, clumsy evidence lists, and a towed trailer described as "no trailer needed".

## Open (UNKNOWN)
- **Wiring is Agent 01's:** the Researcher adapter should pass `profile=` to `research_step`, and the enrichment step should persist `e["provenance"]` before attaching the blocks.
- `listing_activity` from Agent 02 is not wired. The listing-age sentence is tested with a synthetic block.
- Truck-bed fit is "unspecified" in Michael's profile, so heavy items stay UNKNOWN.
- The seasonality sources need a human read before anyone leans on them.
- The penalty and offer percentages are REC placeholders until outcomes calibrate them.
