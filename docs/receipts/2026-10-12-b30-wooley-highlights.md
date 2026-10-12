# B-30 receipt: Wooley highlights list + event category

- **Task:** B-30 (P1, F-146 verification follow-up). Lane 02. DRY-RUN; no network used.
- **Change:** `src/mbos_discovery/adapters/wooley_site.py` only. `parse_detail` now stores the page's `<li>` items (text only, after the event-info block, before "selected highlights only") as `highlights` (list); the former headline is kept as `category_headline`. New field `event_category` (INFERENCE), e.g. `auction event: heavy equipment`. Item `category` is classified from the title only, so the headline's "Trailers" no longer wins. Normalized `description` joins the highlights.
- **Provenance (FACT):** archived T.J. Bruck page `tests/fixtures/wooley/` (wooleyauctioneers.com copy, B-26). Items include "John Deere 750 crawler dozer".
- **Boundary:** no hibid.com request; fetch path unchanged.
- **Tests:** `test_b30_highlights_list_headline_and_event_category` (+ headline assertion updated). Full suite `pytest -q` = **362 passed, 0 failed**.
