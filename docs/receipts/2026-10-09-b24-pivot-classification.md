# Receipt: B-24 pivot classification (lane 02, DRY-RUN)

- **Action:** extended the B-21 tagger (`src/mbos_discovery/tags.py`, `build_pivot`) with trailer subtype / axle, donor camper-RV, log splitter, towable machine, ATV; paperwork status and condition words. Output is `category_tags.pivot` inside the existing enrichment block (card tag enum unchanged, no contract change). `enrichment.py` attaches the block when `pivot` is non-empty.
- **Provenance:** inputs are the sanitized listing `title`/`description` only (B-21 sanitizer, injection fields excluded). Every class is INFERENCE with quoted evidence (field, label, quote, offset). Fixtures `tests/fixtures/pivot_listings.json` are ILLUSTRATIVE, hand-written.
- **Rules:** paperwork exists only where the text states it (silent text gives none, never "no title"/"clean title"); donor RV needs an RV word AND a donor word; negations discard subtype/condition matches. No contact, spend, or live call.
- **Tests:** `.venv/bin/python -m pytest -q` -> 332 passed, 0 failed (13 new in `tests/test_b24_pivot.py`).
