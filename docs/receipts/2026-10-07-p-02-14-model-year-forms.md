# Receipt — READY_QUEUE P-02-14: shorthand model years (`'18`, `MY2018`) for the KB matcher

- **Date:** 2026-10-07 · **Actor:** Agent 02 (bounded worker) · **Task source:** READY_QUEUE P-02-14.
- **External effects:** none. DRY-RUN; pure string logic, no network, no listing was fetched.
- **Code:** `src/mbos_discovery/model_years.py` (`extract_model_years`, `for_kb_match`, `card_line`). Tests: `tests/test_p0214_model_years.py` (29).
- **Provenance:** the title shapes in the tests are hand-written from the forms listed in the task (ILLUSTRATIVE, fictional make FIXMOTORS); no live listing was read, so how often each form appears in real data is UNKNOWN. The four-digit logic stays Agent 03's `listing_years` (unchanged).

## Acceptance — MET
- Reads `'18`, typographic `’18`, `MY2018`, `MY 2018`, `MY-2018`, `MY18`; two-digit years use a pivot (<= 35 → 20YY, else 19YY) inside the matcher's 1950-2035 window.
- Negatives that are not years: `5'10`, `6'18"`, `MY18-4420` and `MY2018A` (part numbers), `PN'18`, `$'18`, `18%`, `'18.5`, bare `18`, `MY1812`, `'47`, `'36`.
- The KB matcher is not changed: `for_kb_match` returns a copy of the Item whose title also states the year in four digits. Verified against `mbos_economics.valueadd.match_hits`: `'18` hits a 2018 entry (the matcher alone does not), `MY2018` against a 2013-only entry is blocked (UNKNOWN), and a part number never becomes a year.
- Card: every extraction carries `basis: "INFERENCE"`, and `card_line` says "INFERENCE: ... seller's shorthand ... not confirmed". It never states a FACT.

## Not done / UNKNOWN
- The helper is not yet called from the pipeline; wiring it where the card's KB hits are built is a follow-up for whoever owns that call (Agent 01 / 03).
- Real-listing frequency of each form (needs live runs, B-12).

Health: `.venv/bin/python -m pytest -q` → 302 passed, 0 failed.
