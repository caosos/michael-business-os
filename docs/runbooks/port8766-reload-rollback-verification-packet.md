# Port 8766 reload / rollback / verification packet (PREPARED, NOT APPROVED)

Prepared 2026-10-10 (ARYA-20261010-0703). **Live reload is NOT approved. Nothing here was executed; the running :8766 is unchanged.** This packet is only for use after staging review and a fresh explicit owner approval (prior reload approval of 2026-10-09 was "used once", see `docs/receipts/2026-10-10-marketplace-8766-reload.md`).

## Candidate artifact (FACT, from lane 06 branch heads)
- Lane 06 `research/agent-06-communications` head `026058e`; code commits F-56 `d89c87c`, F-57 `85c416d`; currently live is `5b42655` (F-48). The reload would carry F-49, F-50, F-51, F-52, F-53, F-54, F-55 (tools/docs only), F-56, F-57 UI code.
- Do NOT reload until F-58 (queue) has produced the committed-artifact final acceptance and the owner has reviewed it.

## Reload (method already used once, per the 02:04Z receipt)
1. Export the verified lane 06 commit, `tools/sync_lanes.py`, stage on :8767 on the same DB; run the acceptance shots/tests there first.
2. Copy `var/lanes/agent-06` to `var/lanes/agent-06.prev-<UTC stamp>` (the rollback copy) BEFORE replacing.
3. Stop only tmux session `mbos-dev-ui`; replace `var/lanes/agent-06/{operator_ui,comms_spec}` with the verified export; start the UI with the same command as `tools/run_dev_stack.sh`. Do not touch the database, `mbos-dev-worker`, approvals, receipts, the 8793 server, CAOSCare or Desktop-Agent.

## Rollback
`tmux kill-session -t mbos-dev-ui; rm -rf var/lanes/agent-06; cp -a var/lanes/agent-06.prev-<stamp> var/lanes/agent-06`, then start the UI as in `run_dev_stack.sh`. Rollback trigger: any verification item below fails, or `/` is not a 200/303.

## Post-reload verification (read-only)
- `GET /` -> 303 `/market`; `/market?go=1&source=gsa&base=Conway%2C+AR&radius=150` shows the cache as-of line and states "cached, not fresh".
- Visible known-section IDs equal the independent cache computation (not counts of all `.mk-g`; hidden unknown cards excluded); original links belong to the displayed lot.
- Real Save click then reopen then app restart keeps categories, condition, row order (F-56 evidence is staging only; this repeats it on live prefs, so use a throwaway saved search and delete it).
- Strict filters: min/max/radius unchanged; unlocated origin never called local.
- No TRAIN-*, `example.invalid`, demo records on `/`, `/queue`, `/mission`, `/summary`.
- Mobile 390 px: no horizontal overflow (price/title still need a scroll; known limitation, do not claim full first-viewport browsing).

## Cache is stale; refresh route (FACT/INFER)
- Cache file `var/cache/gsa-active-auctions.json` (coordinator checkout), sha256 `d02f3acc...a154ba7`, 1,179 lots, fetched **2026-10-10T00:19:23Z**. It is stale, not a fresh hunt. The page labels it "cached".
- Existing supported refresh: lane 02 `GsaAuctionsAdapter` (`src/mbos_discovery/adapters/gsa_auctions.py`), official GSA Auctions API, read-only, tier 1, no live call unless `live=True`. The earlier smoke (`docs/receipts/2026-10-09-gsa-api-smoke.md`) used one GET with the public `DEMO_KEY` (10 requests per window), no account. Production use of `GSA_API_KEY` (api.data.gov) is the adapter's documented credential path and is queue item B-12 (owner decision #8); no new integration is proposed.
- UNK: which exact command currently rewrites `var/cache/gsa-active-auctions.json` (the smoke receipt describes the GET, not a scheduled refresher). Whoever refreshes must record the new sha256/as-of; this packet does not refresh anything.

## Owner decision needed
1. Approve or decline ONE consolidated UI-only reload of :8766 after F-58 acceptance (default: DECLINED / not approved).
2. Optionally approve a single read-only GSA refresh (DEMO_KEY, 1 GET) so listings are current; otherwise stay on the 00:19Z cache.
