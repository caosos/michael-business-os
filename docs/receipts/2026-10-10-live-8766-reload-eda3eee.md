# START: live :8766 UI-only release to eda3eee (A-58)

- Started 2026-10-10T20:54:15Z by the Agent 01 coordinator session, worktree agent-01-coordinator.
- Before: live PID 3887153 (started 2026-10-10T16:47:55Z) serving artifact 2897374 (tree cc444c29...). Script blob 5689c7176b65 = 7c0fbbb.
- Script verifies export + backup before stopping the UI and rolls back automatically.

# RESULT: SUCCESS, no rollback (recorded 2026-10-10T20:55:41Z)

| Item | Value |
|---|---|
| Script | tools/reload_ui.sh, blob 5689c7176b65b8586f8e2bf17c27d47b801ea675 (= reviewed 7c0fbbb), exit 0 |
| Stop / done | 2026-10-10T20:54:18Z / 20:54:30Z (about 12 s downtime) |
| Old UI | PID 3887153, artifact 2897374 |
| New UI | PIDs 4062339 (bash wrapper) / 4062342 (python), started 15:54:20 local = 20:54:20Z |
| Artifact | eda3eee6d303ab6ee1df419b66d54c831d7d8b1d, tree sha256 6e1acdeba53aa954fc3443acc77a6cf6308bc4aa0b23dfcd0395cee51e875587 (ARTIFACT marker, my own recompute and the script's export hash all equal) |
| Backup (verified before the stop) | var/lanes/agent-06.prev-20261010T205417Z (previous: ...T164752Z, ...T020431Z) |
| Identity statement | disk tree hash + restart after swap + semantic route markers; NOT a SHA returned by the running process |

**Independent verification (live :8766, GET only)**
- `--verify-only 8766`: VERIFY OK. /, /mission, /queue, /market respond (303, 200, 200, 200); no fictional training content on /mission or /queue.
- **Search Now** is inside the Filters card (button.mk-go in the sidebar card), desktop and phone screenshots.
- **Distance mode** Conway AR 150 mi: 12 checked cards; chips: "Radius: 150 mi (known distances only); Location mode: By Distance (states not applied)". **State mode** (loc_mode=state): AR 12 cards, AR+TX 31; chip "Location: By State: AR; the radius is NOT applied".
- **Strict filters:** max price 1000 -> 2 cards; radius 10.36 -> 10 cards, 10.34 -> 0 (exact boundary); radius -1 -> "Check your filters" alert, no results.
- **Labels:** gallery cards show "est. next ~$N (cached, unverified) · Reserve: Yes (amount undisclosed)" or "est. next UNKNOWN" when there is no bid.
- Screenshots (real cache, no fixture): docs/receipts/live-8766-reload-eda3eee/screenshots/*.png with JSON sidecars (URL, viewport, filters, capture time 2026-10-10T20:55Z, cache fetched 2026-10-10T00:19:23Z, page shows red STALE 20.6 h). 12/12 checked cards match the cache links/titles; 81 optional links in cache. Raw: docs/receipts/live-8766-reload-eda3eee/behaviour.json, behaviour-state.json, reload-output.txt.

**Observations, not failures:** on a 390 px phone the first result card starts at 1922 px (the stacked filter card comes first; it was 767 px in the artifact before). Cache was NOT refreshed. Live Save/persistence NOT verified: Michael must enter his own PIN; I never read or requested it. Rollback: tmux kill-session -t mbos-dev-ui; rm -rf var/lanes/agent-06; cp -a var/lanes/agent-06.prev-20261010T205417Z var/lanes/agent-06; start as in tools/run_dev_stack.sh.
