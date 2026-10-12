# F-152: auto-detected bids in the My bids window (B-27 wiring)

Provenance: queue row F-152 (owner 2026-10-12 "my system should see that I bid on it"); lane 02 `a186ca6` (contains `mbos_discovery.bid_events`, B-27 `c839030`) pinned the local way (`git archive` to `.tools/disc-a186ca6`, installed with `uv pip install --no-deps`, no `build/`).

What changed (DRY-RUN; no IMAP, no network request, no credential, parser untouched):
- `operator_ui/market_autobids.py` (new): `read_bid_events` over an `EmlDirReader`, only when `MBOS_STAGING_FIXTURES=1` AND `MBOS_BID_MAIL_DIR` is an existing directory. One row per listing: latest lifecycle event headlines, earlier events listed, amount only when the e-mail stated it (owner-local, this page only, not stored), close time when any e-mail stated it else UNKNOWN, provenance = e-mail Message-ID, label "auto-detected from your e-mail". DKIM-failed mail yields no record (parser rejects it).
- Without the flag: one line "Automatic bid detection is not connected (no mailbox)." in the window (the live configuration).
- A result card with the same listing link (normalised host/path) is excluded from results, unchecked and finds, and counted in "N in My bids", exactly like an owner-marked one.
- "Stop tracking" on an auto item stores its id under `auto_stopped` in the owner-local market prefs (kept by reset); the mail is never touched.
- `market_bids.window` merges auto rows with owner-marked rows by close time.

Tests: `tests/test_market_f152.py` (7), fixtures = lane 02's synthetic `bid_mail/*.eml` copied to `tests/fixtures/bid_mail/`. Full health result is in AGENT_STATUS. Not done: Chrome desktop+mobile screenshots (Agent 01 verifies). Real notification wording is UNKNOWN (B-27: re-record on the first real e-mail).
