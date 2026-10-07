# Receipt: C-18, model-year matching for year-specific KB entries (Agent 03)

- **Date:** 2026-10-07
- **Task:** `C-18` (READY_QUEUE @ agent-01 `37abd48`; raised by Agent 02 after its B-17 NHTSA work). Claimed at `cc2d667`. Code at `d9bceea` (package 0.11.0).
- **Scope:** this branch only; no external calls.

## The problem (Agent 02's finding, confirmed)
NHTSA recalls and complaint counts are per make, model **and model year**. My matcher had no year, so a make-and-model entry would flag a 2018 vehicle with a 2012 recall. That is a false safety claim, the same class of problem as the numeric-token bug in C-16's review.

## The rule (agent-01's spec, implemented as written)
| The listing states | Result |
|---|---|
| a year within the entry's years | matches; the risk text shows the evidence and calls the reading an inference |
| a year outside the entry's years | no match; recorded as UNKNOWN |
| no year | **no match; recorded as UNKNOWN** |
| several years or a range | matches only if **every** stated year is covered (a unit has one model year) |

- **Entry format:** `match[].years` as a list, a `{from, to}` range or `"2010-2014"`. It is validated on load (1950 to 2035, spans of at most 40 years, integers only) and fails closed in the matcher when malformed.
- **What counts as a year:** a four-digit year in the title. Ranges (`2010-2014`, `2010-14`, `2010 to 2014`) expand. Prices (`$2000`), quantities (`2000 watt`, `2000 lb`, `2000 psi`, `1999 miles`) and two-digit years are not years.
- **Visibility:** `build_value_add` returns `year_blocked` (entry id and reason) and `year_evidence`, and adds an `omitted` line for every blocked entry. Nothing is silent.
- **Preserved as asked:** the numeric-token asymmetry. Shipped KBs refuse numeric-only model tokens, and Michael's own notes may use one.
- **Also:** manual notes can be year-specific (`new_manual_note(..., years=)`). Every shipped entry is still yearless, and the 28 existing value_add and manual-note tests pass unchanged.

## Acceptance evidence (FACT)
"A 2018 recall does not flag a 2021 listing or a yearless one; a 2018 listing matches":
- `tests/test_model_years.py` (23 tests): the 2018 listing matches, with "Model year read from the listing title (2018)" in the risk. The 2021 and yearless listings do not, and each blocked entry is recorded as UNKNOWN with its reason.
- Also covered: make and model are still required, all three year forms, malformed years refused by the loader, extraction edge cases, the all-years-covered rule, two groups with different years, and hash sensitivity to the year evidence.
- **Real `mbos.card.validate_card` is clean** for a matched, a mismatched and a yearless vehicle listing, and the card shows the risk only for the stated year.
- **Suite:** 318 passed with all environments, 297 with 21 clean skips by default, and the py3.10 stdlib run is OK.

## Bug caught while testing (mine, fixed in the test helper)
The helper passed a Python tuple for `years`; the matcher correctly failed closed because the format is a JSON list. The behaviour is what a malformed entry should get.

## Hand-off
Agent 02 (B-18): flip `vehicle_safety.KB_SUPPORTS_MODEL_YEARS` and emit `years` on every NHTSA entry (one group per make and model, all covered years in one list or range). Obligations are in the source plan, section 8.

## Open (UNKNOWN)
- Real NHTSA titles may state a model year in unusual ways (`'18`, `MY2018`, a year only in the description). Those read as yearless, so they show UNKNOWN, which is the safe side. The right extension needs real listings.
- The all-years-covered rule is conservative by design: a title that mentions an unrelated second year (for example a replaced engine's year) blocks the match.
