# A-60: hide listing (X) + hidden list + per-item undo (lane 06, DRY-RUN)

Provenance: queue row A-60 (owner request: dismiss unwanted, show remaining real ones); staging evidence from committed code a9be4e4 (dirty:false), STUB store, copy of the real GSA cache (as-of 2026-10-10T00:19:23Z, sha in `docs/receipts/a60-hide-screenshots/evidence.json`). No bids, purchases, GSA sign-in, fetch, spend or credentials.

## What changed
- `market_prefs`: new durable `hidden` {stable listing ID: title}; old `dismissed` ids migrate into it on load. New actions `hide` (X) and `restore`. `hide` touches NO learning weights and does NOT remove saves. `Not interested` (`dismiss`) is now explicitly separate: hides the listing AND counts its title words as "less like this" (honest tooltip + message; Undo restores visibility but does not unlearn). `reset` clears saves/likes only; hidden listings stay hidden.
- `market_routes`: `mp.hide` runs on BOTH the checked and the unchecked section, whether suggestions are on or off; remaining listings keep the strict filter results unchanged (hide only removes, never adds or relaxes).
- `market_view`: distinct X / "Hide this listing" button bottom-right of every gallery and list card (`aria-label`, native button = keyboard operable); learning buttons carry effect labels; "Hidden listings" panel with per-item "Undo hide"; exhausted state says 0 left, nothing substituted, no new fetch, no guaranteed replacement.
- Photo note: GSA photos stay behind GSA login; no account integration or scraping added; verified original-listing link remains the fallback. Real access dependency = an owner-authorised GSA session, not built.

## Tests
`tests/test_market_a60.py` 9 passed (X a11y, toggle on/off + restart, unchecked section + individual undo, learning weights unchanged, Not interested separate, strict-filter/no-refill, exhausted, saved preserved, migration). Updated two F-52 tests to the new contract. Reference suite: 428 passed / 1 failed (known `test_resale_f39` timeout). Lane D+E: 105 passed / 2 failed (known F-32). 
## Real interaction (real Chrome, separate server processes, restart pid 112519 -> 112715)
Mouse click X, keyboard Enter on X, unchecked-section hide, toggle off/on, process restart, Undo one, exhaustion; all recorded in `evidence.json`. Shots: desktop 1648x1000 and mobile 390x844 in `docs/receipts/a60-hide-screenshots/`.

## Not done / honest limits
Release is NOT done; live :8766 needs the existing bounded release review. Status ACK/queue/actualSTART are Agent 01's to report.
