# F-145: /market source seam (B-12 implementable sub-step, not a second source task)

Provenance: queue row F-145; spec `docs/handoff/B12_LOCAL_SOURCE_WIRING_SPEC.md` (coordinator branch); lane 02 `mbos_discovery.adapters.email_alerts` (pinned install in `.venv`, `EmailAlertAdapter` + read-only `EmlDirReader`; `.eml` fixtures copied unchanged from lane 02 `tests/fixtures/email/` into `tests/fixtures/alerts/`). DRY-RUN. No IMAP login, no network, no secret, no new dependency, no DB change.

## Change (code_sha `2136743`, dirty=false)
- `operator_ui/market_sources.py` (new): `load_source(source, ...)` returns the `load_gsa` dict/card shape for gsa | govdeals | publicsurplus | all. Per card: source name, source link, price (`bid` only for a current bid, else `price`/`price_type`, as GSA treats no-bid), town + distance (gazetteer, then `place_coords`; unresolved = unchecked, never local), `fetched_at` = the alert e-mail Date, `stale`. Spoofed/unauthenticated mail is quarantined by the lane 02 parser (never shown). `all` merges and de-dups (same link, or title similarity >= 0.9 in the same place); lane 02's pinned install has no `Deduper` class, so `dedup.title_similarity` is used.
- `operator_ui/market_search.py`: thin `load_source`. `market_routes.py`: dispatch on `q['source']`; filters (price, radius, origin, states, keywords, categories, hide) run unchanged on all cards.
- `operator_ui/market_source_view.py` (new) + small `market_view.py` edits: per-source status rows; FIXTURE banner; NOT CONNECTED for any source without a read.
- Parser-backed `.eml` records are served ONLY when both `MBOS_STAGING_FIXTURES=1` and `MBOS_MARKET_FIXTURE_MAIL_DIR` are set (isolated staging); labelled "FIXTURE / not live", never "connected". Without them GovDeals/Public Surplus are NOT CONNECTED. Craigslist, eBay, Facebook Marketplace stay NOT CONNECTED always. No path in this change can report "connected" for a mailbox source.
- `tests/test_operator_ui.py`: module allowlist gained the two new modules.

## Tests
- New `tests/test_market_f145.py` (12) + `tests/test_market_f145_golden.py` (1): card-shape parity, provenance/freshness, filters on parser-backed records, `all` de-dup, FIXTURE present / "connected" absent, no-read source NOT CONNECTED, no flag = no listings, no IMAP/network in the seam.
- GSA golden: committed from the pre-change code's output (5 pages), masked only for csrf/nonce, cache age, and the Source `<select>` (which intentionally gains choices); the new output is byte-identical after masking.
- Full run (tools/run_tests.sh) before the allowlist fix: reference 476 passed / 2 failed (`test_resale_f39` known timeout; `test_ui_owns_no_gateway...` caused by this change, fixed in `2136743`, re-run alone: passes; the full reference suite was not re-run end to end after the fix, so the expected figure is 477 / 1); lane D+E 105 passed / 2 failed (known F-32).
- `tools/f143_live_check.py`: 32 checks, 0 failed, dirty=false. `tools/f142_live_check.py` (from the coordinator branch, against an isolated staging server on a copy of the real GSA cache): exit 0 (an earlier attempt failed only because the server was not yet listening).
- `tools/f145_source_shots.py`: real Chrome (channel chrome) desktop 1648x1000 and mobile 390x844, 22 checks, 0 failed, dirty=false; screenshots + `f145-evidence.json` in `docs/receipts/f145-source-seam-screenshots/` (I reviewed the desktop and mobile fixture gallery shots; Agent 01 review pending).

## Not done / still open (honest)
- NOT live: no real mailbox read exists, so GovDeals/Public Surplus are not "connected". LIVE acceptance stays in B-12 (mailbox NEED).
- Not released: no `tools/reload_ui.sh` run by me; loaded revision on :8766 unchanged. Host observation: staging servers on loopback only, stopped. Cost: not known.
- Fixture mail dates (2026-10-07) read STALE by the 6 h rule, which is correct for old fixtures.
