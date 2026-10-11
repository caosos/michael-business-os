# F-141: owner-entered finds (Facebook, Craigslist, OfferUp, other) on /market

Status: DONE, DRY-RUN, staging only (scratch files, loopback). No live change, no :8766 reload.
Provenance: queue row F-141 (owner, 2026-10-11: "build the sources other than GSA: Facebook, Craigslist"), added by 01.

## Scope note (what was inspected and reused)
- `/intake` (`intake_view.py`, in-memory drafts): NOT reused for storage (drafts are in memory); its "owner-supplied, unverified" wording is mirrored.
- "Add a listing" owner form (`live_demo.render_owner_form`): form/CSRF pattern and `link_html` (the only way a URL becomes markup; `classify_url` rejects fixture hosts).
- `bought_view.py` / `wanted_view.py`: owner-local JSON + CSRF-only POST pattern; not changed.
- `market_prefs.py`: JSON file path/atomic-write pattern copied; Hide/Save/Not interested/Undo reused unchanged by stable id (one-character change: ids may now contain `:`, GSA ids never do).
- `market_search.partition`: reused as-is, so price, radius (unrounded haversine), state, category focus and condition behave exactly like GSA.
- `gazetteer.locate`: city/state/ZIP resolution; unresolved -> distance None -> unchecked, never counted as local.
- `precedent_view.for_cards` (F-139): now passes the card's `source_key` (default "gsa") so finds get the decision-case block.

## What was built
- `operator_ui/market_finds.py`: validate, store (`var/market_finds.json` beside `market_prefs.json`, `MBOS_MARKET_FINDS_FILE` override, atomic temp+fsync+replace), id `own:<source>:<sha256[:12] of normalised link, else title|location>` (link query/fragment/trailing slash ignored), duplicates refused, edit, soft delete + undo, audit (`created_by/at`, `updated_by/at`, `deleted_by/at`; who = "owner (Operator UI)"), card builder. No network import.
- `operator_ui/finds_view.py`: "Add a find" form (link, title, price optional, City ST or ZIP, condition, source facebook/craigslist/offerup/other, notes) and the "Your finds" section: OWNER-ENTERED / not fetched / unverified / not a live listing, source label on every card, unchecked list, deleted-finds list with Undo.
- `market_routes.py`: `POST /market/find` (CSRF only; nothing is sent, fetched or spent), section passed to `market_view.render_page` (separate from GSA results and counts).
- The link is stored as text; the only request ever made for it is the owner's own browser click on the anchor.

## Evidence
- Focused tests `tests/test_market_f141.py`: 13 passed / 0 failed (add+validate, section/labels, GSA count unchanged and no mixing, persistence + no temp files, duplicates incl. tracking-param links and title+city key, edit + audit, soft delete/undo, price + unknown price, radius boundary (exactly on = in, 0.001 mi under = out), unknown location unchecked, state/condition/category, hide/restore/dismiss/save by id, F-139 block on a find, hostile text escaped, no network: source has no urllib.request/requests/socket/http.client import and `socket.connect`/`getaddrinfo`/`urlopen` patched to raise while add + page render still work, no `var/private` in output).
- Staging screenshots (real Chrome, stub store, test GSA fixture, scratch finds file, synthetic finds) in `docs/receipts/f141-finds-screenshots/` with `evidence.json`: all Chrome requests loopback (`chrome_requests_all_loopback: true`, no external requests), duplicate refused visibly, GSA heading unchanged by finds, hide/undo and delete/undo work. Tool: `tools/f141_finds_shots.py`.
- Full suites: reference 457 passed / 1 failed (known resale_f39 timeout; first run also caught my button-class clash with f60 and the module allowlist in test_operator_ui, both fixed); lane D+E 105 passed / 2 failed (known F-32).

## Limits / UNKNOWN
- Default /market focus (trailer, equipment) also hides finds that do not match it (same strict category terms as GSA); the section says how many are hidden by filters.
- A ZIP-only location has no state in the small local gazetteer, so in By State mode it is unchecked (state unknown), not guessed.
- Editing a find's link/title/place changes its id (earlier Save/Hide on the old id stop applying; the old id is kept as `former_id`).
- Single owner, so `who` is a fixed label, not an identity.
- Release to the live :8766 UI only through the existing bounded release review.
