# Live :8766 reload and rollback packet (PREPARED, NOT APPROVED, NOT RUN)

Prepared by Agent 01 in commit `206e484` (committed 2026-10-10T07:15:50Z). **No live reload has been approved.** The F-48 reload authorization (02:04Z) was used once. This packet is the one narrow decision the owner would make.

## What is live now (observed)
- :8766 runs `mbos-dev-ui` PID 3235972, started 2026-10-10T02:04:45Z, loading the **F-48** export from `var/lanes/agent-06` (F-49 to F-57 are NOT live). Landing redirects to `/market`; `/mission` `/summary` `/digest` `/ledger` still show the fictional TV; no min/max price, no browse-first gallery, rounded radius.

## The artifact
- Lane 06 `research/agent-06-communications` @ **`026058e`** (F-57 `85c416d`/`ebdb158`; includes F-49 to F-57). Final evidence: `docs/handoff/F-51-F-52-acceptance-matrix.md` (39 PASS / 6 PARTIAL / 1 FAIL / 0 NOT RUN on this artifact, with who ran what; A17 FAILS: a saved search drops its 'any of' focus terms, fix queued as F-59), screenshots `docs/receipts/f57-real-cache-screenshots/`, `docs/receipts/f57-save-restart-proof/`.
- Gates on `026058e`: reference 380 passed / 1 failed (`test_resale_f39` socket TimeoutError in the full run, passes alone 4/4: unresolved, not a pass); lane D+E 105 passed / 2 failed (known F-32 pair). Not all green.

## The change (one command, after approval)
`cd ~/business-os-worktrees/agent-01-coordinator && tools/reload_ui.sh 026058e`
- Verifies the commit is on lane 06's pushed branch, exports exactly it, backs up the current UI to `var/lanes/agent-06.prev-<UTC>`, stops ONLY tmux session `mbos-dev-ui`, replaces `var/lanes/agent-06/{operator_ui,comms_spec}`, restarts the UI with the same command as `tools/run_dev_stack.sh`, health-checks `/market`.
- **Downtime:** about 11 s (measured 02:04:43 to 02:04:54Z last time). **Affected process:** `mbos-dev-ui` only. **Not touched:** database, `mbos-dev-worker`, dispatcher, pickup watcher, watchdog, approvals, receipts, Desktop-Agent, CAOSCare.
- **Automatic rollback:** if `/market` is not HTTP 200 after the restart, the script restores the backup and restarts the old UI, then exits 1.
- **Manual rollback (any time):** `tmux kill-session -t mbos-dev-ui; rm -rf var/lanes/agent-06; cp -a var/lanes/agent-06.prev-<UTC> var/lanes/agent-06`, then start the UI as in `tools/run_dev_stack.sh`. The existing `var/lanes/agent-06.prev-20261010T020431Z` is the F-48 predecessor of today's live code.

## Verification after the reload (Agent 01 runs these; evidence goes to GitHub)
1. `GET /` -> 303 `/market`; `/market` 200; zero TRAIN-*, `example.invalid`, "55 inch", "LED TV" on every nav route (route walk, as in `docs/receipts/2026-10-10-f49-verification.md`).
2. `tools/capture_market.py --port 8766 --sha 026058e`: real-cache screenshots and the listing-ID/link comparison against `var/cache/gsa-active-auctions.json`.
3. Strict limits (max price, radius 10.35 vs 10.36 boundary) and the validation messages on the live page.
4. Saved-search persistence on the LIVE database needs the owner's PIN: this is the part Agent 01 cannot do; the owner clicks Save, reopens, and (optionally) the UI is restarted. Until then persistence is proven only on an isolated stub store.

## Known limits that remain after the reload
- **Saved searches silently drop their 'any of' focus terms (matrix A17 FAIL, ARYA-0717)**: reopening a saved search can broaden it. Recommended: do not rely on saved searches until F-59 lands; this is a reason to wait for F-59 before the reload if the owner wants saved searches.
- GSA photos need a GSA login: cards show a tile, never an image. Desktop is denser but not five-across everywhere (matrix B01 PARTIAL); on a phone the first card's price and title need scrolling (B03 PARTIAL). With categories checked, the Row 1-4 selectors are retained but not used for display (rows apply when none is checked). The cache is stale (fetched 2026-10-10T00:19Z) and the page says so.

## Cache refresh (existing supported route, nothing new)
- The UI only READS the cached file `var/cache/gsa-active-auctions.json`; it never fetches. The only supported fetch path is `mbos_discovery.gsa_live.GsaLiveAdapter(cache_path, live=True).fetch(profile)` (lane 02, B-25): one logical fetch per run (the API call plus its 303 to a signed file), cache reused for 1 hour, public `DEMO_KEY` (10 requests per window) unless the owner provides `GSA_API_KEY` (a personal api.data.gov key is an owner decision; none exists and none was requested). No new integration, credential or paid service is needed for a DEMO_KEY refresh.
- **No one-command wrapper exists** for it (the adapter needs a `SearchProfile`). A ~15-line wrapper script would be a small task for lane 02 if the owner wants a refresh; nothing was fetched for this packet.
