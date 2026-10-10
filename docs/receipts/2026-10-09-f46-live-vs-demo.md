# F-46 receipt: live vs demo separation in the Operator UI (DRY-RUN)

- **Task:** F-46 (P0), lane 06, branch `research/agent-06-communications`. Depends on F-45 (DONE); B-25 (GSA adapter) is READY in lane 02 and NOT landed, so the GSA card is built on the queue's documented lot shape and fed by a local file (`MBOS_GSA_LOTS_FILE`), not a live fetch.
- **Provenance (FACT):** TRAIN-* fixtures are `fixtures/sources/training_examples.json` on the coordinator branch (A-41): `source_listing_id` `TRAIN-*`, URLs `example.invalid`, dry-run bankroll $500. Owner directive is the F-46 row of READY_QUEUE.
- **What changed:** new `operator_ui/live_demo.py`; `server.py` (Today, `/resale`, item page, `/owner-listing`, `/gsa`, nav); `card_view.py` (header link); `comps_view.py` (needs block); `deal_ui.py` (demo link text); `resale_view.py` (bankroll label).
  1. **Classification:** an item is DEMO if it is TRAIN-* (source id, dedup key, or item id) or has no source with a real http(s) URL on a non-reserved host.
  2. **Normal feed:** Today's queue, glance cards, "Research needed" list and the resale DEMO lots exclude DEMO items. A one-line note says how many are hidden and links to `/?demo=1`.
  3. **DEMO switch** (`?demo=1` on `/` and `/resale`): banner "DEMO / TRAINING DATA, NOT REAL LISTINGS, DO NOT BUY"; demo rows are listed by title in a separate section, with no decision buttons and never under "Needs your decision". The item page of a DEMO item always carries the banner.
  4. **example.invalid** is never an `<a>`: shows "No real listing, training example". The item-card header uses the same function.
  5. **No sold evidence:** headline is "RESEARCH NEEDED, DO NOT BUY YET"; the add-a-price form sits under Details (no "look at an item" prompt).
  6. **Bankroll:** the $500 is labelled "DEMO bankroll (source: dry-run ledger; as of <time>)", real cash is "UNKNOWN until you enter it", and no recommendation is made from it.
  7. **Unknown fields:** `live_demo.collapse_unknown` folds UNKNOWN rows into one counted `<details>` line (helper, used by the new cards; the existing F-13 card keeps its per-field UNKNOWN reasons: INFER that those are the card contract's honesty rules).
  8. **Owner-supplied intake** (`/owner-listing`, CSRF, no PIN, in memory): URL + photo links + pasted text, marked OWNER-SUPPLIED with author and time, escaped, status RESEARCH NEEDED. Nothing is fetched or sent; links need an allowed host.
  9. **GSA card** (`/gsa`): original link, photo, location, high bid, bidders, end time, as-of; bid is not a sold price; buyer premium and sold comps UNKNOWN.
- **Limits (UNKNOWN/REC):** the demo section lists rows only (to decide a demo item open its page; the controls there are unchanged DRY-RUN). REC for 01: when B-25 lands, point `MBOS_GSA_LOTS_FILE` at its cache or give the UI a store reader. The existing tests that read fixture items in the queue now use the DEMO switch.
- **Tests:** `tests/test_live_demo_f46.py` (9). Suite numbers are in AGENT_STATUS.
