# Receipt: C-28 the engine reads Michael's service quote (F-32 engine half)
Tags: FACT / INFERENCE / UNKNOWN. DRY-RUN; nothing sent, spent or published.

- FACT: `economics/src/mbos_economics/inputs.py` `quote_override(item)` reads the last valid `Item.research` entry `field = quote:amount_usd` on a SERVICE item (D-30 `record_human_input`, human provenance `prov_...`, named `entered_by`, basis not UNKNOWN, finite number 0 < v < 1e7). `estimate_item` merges it as the `job.quoted_revenue` override; the assumption note reads "human-attested override (prov_...): quote set by <who>" and the provenance `derived_from` includes the human id. Flips ignore it.
- FACT: a quote below cost is accepted as stated; the verdict follows the numbers ($100 -> PASS on the pph floor). `min_quote_for_yes` (the card's "a quote of $X or more would clear it") is still computed from the final inputs and stays the suggestion.
- FACT: acceptance, drywall lead with scope and customer attested (C-25): $700 quote -> YES (composite 63.95, $85.11/h EV); $500 -> MAYBE ($58.18/h EV < $75 target). Default quote $610 unchanged without an entry.
- FACT: no engine, config or version change; existing outputs are byte-identical, so no golden needed regeneration (goldens replay in the suite). Tests: `tests/test_c28_service_quote.py` (6). Suite: 387 passed, 22 skipped (was 381).
- INFERENCE: without attested scope/customer a $700 quote alone stays MAYBE (confidence 0.15 blocks YES); the quote is a price, not evidence, by design.
