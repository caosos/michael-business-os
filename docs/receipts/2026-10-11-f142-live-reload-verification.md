# Receipt — F-142 live :8766 verification (Agent 01, independent)
Observed 2026-10-11T21:31:05Z. Provenance: FACT = observed this session by command; UNKNOWN = not observed.
- FACT: live `var/lanes/agent-06/ARTIFACT`: `sha=85246899debf5c9b8af418dc5560f3b01273d5ee`, `tree_sha256=de49e8238daabb839bf711efb71abc5080bc5c9de7f3b263c795c1e8d37396b9`, `exported_utc=20261011T212259Z`. Listener on 127.0.0.1:8766 is PID 725190 (tmux `mbos-dev-ui`). Previous live was `63d741d` PID 592603.
- FACT: backup `var/lanes/agent-06.prev-20261011T212259Z` has `sha=63d741d…` (the predecessor), so rollback material exists.
- FACT: on-disk `operator_ui/market_view.py` sha256 prefix equals `git show 8524689:operator_ui/market_view.py` (80e90fbf64118020).
- FACT: `tools/reload_ui.sh --verify-only 8766` = VERIFY OK. `tools/f142_live_check.py 8766` exit 0 (`docs/receipts/f142-live-verification/live-check.json`): desktop 1648x1000 click, mobile 390x844 click, desktop Enter; Search Now is last after every visible filter control and below both sliders; Min 5 / Max 25 changed the page 134 -> 97 lots each time. I read the desktop screenshot (`live-desktop-click.png`): button last in the filter card, applied-filter chips show Min $5 / Max $25.
- FACT: GSA cache sha256 prefix `7eb8efd4b6d7be71` before and after (not refreshed); cache as-of 2026-10-11 02:48 UTC, the page labels it STALE.
- FACT: watchdog health `:8479` HTTP 200, generated_at 2026-10-11T21:29:12Z; five MBOS tmux sessions present.
- Executor: the owner, per the liaison message from his screenshot (script output: prerequisites OK, verified backup, baseline /market 200, stop 21:23:00Z, done 21:23:12Z); Agent 01's 21:17Z attempt was denied by the permission classifier and did not run. The script console output itself was not seen by Agent 01 (screenshot-reported). Not observed: the owner's PIN Save on live (an owner action; never read).
- Not claimed: continuous running of any service; only observations at the timestamps above.
- Cost: none incurred by this verification (local only); lane 06 worker cost for F-142 is recorded in its own telemetry, otherwise UNKNOWN here.
- Re-verified 2026-10-11T21:33:58Z: ARTIFACT sha=85246899, listener PID 725190 (started 21:23:02Z), --verify-only OK, tools/f142_live_check.py 8766 exit 0 (3/3 rows, 134->97), cache hash unchanged, :8479 HTTP 200.
- Verdict: **F-142 LIVE_VERIFIED by Agent 01; owner acceptance pending.**
