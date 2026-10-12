# Agent 01 — RESUME HERE (fresh session after a restart)

Written 2026-10-12 ~04:05 CDT by the previous Agent 01 session (restarted to save usage). Read this first, then verify against the repo; repo truth wins over this note.

## First 5 minutes
1. `git fetch -q origin && git status -sb` (branch research/agent-01-coordinator; fast-forward if behind).
2. Read `docs/status/AGENT_STATUS.md`, then the rows marked READY / PARTIAL in `docs/status/READY_QUEUE.md`.
3. Check the host: `tmux ls` (expect mbos-watchdog, mbos-dev-ui, mbos-dev-worker, mbos-pickup, mbos-dispatcher), `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8766/market` (200), `head -1 var/lanes/agent-06/ARTIFACT`, `gh auth status` (logged in as caosos).
4. Inbox: unacknowledged messages = files in `origin/liaison/aria-to-agent-01:docs/messages/inbox/` without a same-named file in `docs/messages/acks/` (the watchdog matches ACKs BY FILE NAME — one ACK file per message id).
5. Record every checkpoint with `tools/eta_checkpoints.py` (ACK/WORKING need a scope-based ETA and an exact `YYYY-MM-DD HH:MM CDT` next check; DONE early as soon as verified). The watchdog relays events to PR #1.

## State at handoff
- **LIVE (:8766):** lane 06 `bbc80ec` + lane 02 `a186ca6` (owner-run release 2026-10-12 05:51Z; verified in Claude in Chrome): GSA, Wooley, Wilson, Blackmon connected; My bids; Census distances; radius slider; DealSniffer Marketplace title.
- **READY TO RELEASE (owner runs it; Agent 01's own reload runs are denied by the permission classifier):**
  `cd ~/business-os-worktrees/agent-01-coordinator && tools/release_marketplace.sh a0ee24051fb06dcab8f04306bcb7da54504c5ece a186ca6e29f785e7bbb705ce6eb44482558f26da`
  adds F-154 closing-soon badges, F-155 ranked Suggestions + owner resale-price input, F-156 Sources panel. After it runs: `tools/reload_ui.sh --verify-only 8766`, check ARTIFACT, then Claude in Chrome on the live page (the owner's Chrome reaches :8766 but NOT staging ports).
- **Running in the watchdog:** A-71 ETA checkpoints + PR #1 relay; A-72 hourly GSA + auction-house cache refresh (off switch: `var/watchdog/refresh.off`).
- **Done but not wired into the UI:** B-27 bid e-mail parser, B-35 HiBid registration records (live needs the B-12 mailbox).

## Open owner decisions / NEEDs
1. Run the release command above.
2. Gmail app password via `tools/setup_alerts_mailbox.sh` (B-12: GovDeals/PublicSurplus alerts, automatic bid detection, HiBid registrations). Local config is `~/.config/mbos/discovery-alerts.toml` (outside the repo); the classifier refused recording mailbox setup in the queue once — do not route around it.
3. The Family Flips (Conway, Shopify): only via its published UCP catalog endpoint, after the owner confirms (terms ban crawling). Other vendors: see `docs/handoff/B12_CRAIGSLIST_FACEBOOK_SOURCE_STATUS.md`.
4. Lot-level data for HiBid/BidWrangler/Proxibid auctions needs written permission or an auctioneer feed (never scrape).

## Next build candidates (queue first)
- A-72: confirm the first live hourly GSA refresh by the watchdog (receipt `cache_refresh_gsa_refreshed`).
- B-34 remainder: wire B-35 registrations into a 'Registered / tracked auctions' list (after the mailbox), more vendors only through lawful paths.

## Hard-won rules (do not relearn them)
- Before launching `tools/worker.py` by hand, check for a running python `tools/dispatcher.py`; it auto-launches READY rows (a duplicate pair ran once). Record a WORKING checkpoint only after confirming the worker PID is alive.
- A row is executed the moment it is pushed as READY: make it correct first; no literal `|` in cells; unique ids (the foreman warns on duplicates).
- Never trust a worker's DONE: verify from a clean detached checkout (`git worktree add`), link lane 06's `.tools`, run focused + full suites, review diffs (goldens token by token), and browser-check.
- Tests that call the watchdog `cycle()` must never touch the live system (autouse fixture in tests/unit/test_coordinator_watch.py).
- `pgrep -f`/`grep` on process text matches your own shell: match the python argv instead.
- The live UI uses the coordinator `.venv`: lane 02 packages must be installed there (the release script does it with a backup).
- Known flake: `tests/test_resale_f39.py` times out in full runs, passes alone.
