# B-40 receipt: per-user alert-mail ingest (ADR-0015 section 5; DRY-RUN)

- **Provenance:** queue row B-40; ADR-0015 (lane 04 `3094eca`); registry seed from lane 04 D-38 commit `b0cb55e` (`git show b0cb55e:config/sources.v1.json`), sha256 `bd0f4d20f65a5de374f777282c00970e80140739a5020531f9ff333d4a965df3`, pinned in `src/mbos_discovery/data/PINNED.md` and checked by `test_registry_copy_matches_pinned_d38_hash`.
- **Change:** `src/mbos_discovery/peruser_alerts.py`. `ingest(reader, handles)` resolves the `To:`/`Delivered-To` plus tag (`alerts+<handle>@`) to a user. Missing or unknown tag, failed DKIM or unparsable mail goes to quarantine (counted; body never parsed for a missing/unknown tag; only reason, date, Message-ID, tag kept), visible via `quarantine_view(viewer_is_owner=True)` only. Listing facts are stored once per (source, posting id), newest alert wins; each user gets an `Interest(user, source, listing, received_at)` row and a per-user last-received alert state.
- **Safety:** reuses B-06/B-36 read-only readers (`\Seen` unchanged), DKIM-gated `parse_alert`; no network, no listing-site fetch, no sends. Fixtures `tests/fixtures/peruser_mail/` are synthetic.
- **Side fix:** `tests/test_location.py` updated for the D-38 registry (three AR auction houses + `ar_state_surplus` replace `ar_local_auction_houses`).
- **UNKNOWN:** whether Craigslist accepts a plus-addressed alert address (ADR-0015 `[UNK]`); verify with one real alert. Persisting interest rows to `mbos.user_item_interest` is not wired here (no live DB in this lane).
- **Result:** full suite 437 passed, 0 failed.
