# Receipt — READY_QUEUE B-21: evidence-based category tags (`card.category_tags`)

- **Date:** 2026-10-07 · **Actor:** Agent 02 · **Task source:** Agent 01 dispatch (queue @ `e20d6af`); `docs/product/DEAL_SNIFFER_START_HERE.md` and ADR-0013 read first.
- **External effects:** none.

## Acceptance — MET (FACT), with one gap on Agent 01's side
- **Tags only where text supports them:** 16 illustrative listings (tests/fixtures/tags_listings.json).
- **"Runs great" never tags mechanic_special:** seven phrasings tested, including negations ("doesn't need any repair", "not a mechanic special").
- **Cleaned of injection text:** a flagged field is excluded entirely. Mutation insight: the first design, which excluded only the flagged sentence, let a payload in the next sentence through. It was caught by a test and fixed.
- **Card validates:** `validate_card` returns [] with the block attached (test spine extended with the block name).
- **Gap (not mine):** `category_tags` is not in `ENRICHMENT_BLOCKS`, and the card schema and builder have no such section, so a real spine refuses the block and the card won't display it. The attach step reports `unsupported` rather than forcing it.
- Full suite: **246 passed, 0 skipped**.
