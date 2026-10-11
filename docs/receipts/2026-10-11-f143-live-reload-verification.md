# Receipt — F-143 live :8766 verification (reload executed by the owner)

Observed 2026-10-11T23:02Z by Agent 01. Provenance: FACT = observed on this host by command; OWNER = from the owner's pasted shell output (liaison message 2026-10-11-owner-f143-reload-started).

- OWNER: Michael ran `tools/reload_ui.sh 315ddfa98ff951e9da716f5b49c37f016153c466` from the coordinator worktree at about 17:50 CDT. Pasted output: prerequisites OK; export tree `b79816a3…`; verified backup `var/lanes/agent-06.prev-20261011T225049Z`; baseline `/market` HTTP 200 with the marketplace marker; stop 22:50:50Z. His paste ended there (no done line shown).
- FACT (completion, read 23:02:21Z): `var/lanes/agent-06/ARTIFACT` = `sha=315ddfa98ff951e9da716f5b49c37f016153c466`, `tree_sha256=b79816a3ded18856f26a07a35765496fa2c9d32683bdb81272bf4b3b384632fe`, `exported_utc=20261011T225049Z`. New listener PID 793565 on 127.0.0.1:8766, started 17:50:52 CDT (22:50:52Z), tmux `mbos-dev-ui` recreated 17:50:52. No `reload_ui.sh` process still running. So the script swapped and restarted 2 s after the stop; no rollback occurred (the marker names the new SHA and the backup holds the predecessor).
- FACT: `/` 303, `/market` 200. (`/health` is 404 on the UI because the UI has no such route; health is the watchdog's `:8479`.)
- FACT: `tools/reload_ui.sh --verify-only 8766` = VERIFY OK.
- FACT: `tools/f142_live_check.py 8766` exit 0: Search Now last after every filter, below the price and radius fields, desktop and mobile; Min 5 / Max 25 changes results 134 -> 97 by click and by Enter.
- FACT (live radius, read-only GET navigation, `docs/receipts/f143-live-verification/live-radius.json`): price sliders absent; radius slider visible with bounds "0 miles" / "25,000 miles"; slider at 0, 60, 120 shows "0 miles", "60 miles", "120 miles" and submits the same `radius=` value; typed 97.9 shows "97.9 miles" and submits it. Live known results 0 / 0 / 6 (staging copy gave 0 / 11 / 19): FACT, the live page states 12 listings are hidden by the owner and 134 lots have no known distance, so lower live counts are expected; the predicate still changes with distance.
- Screenshot read (`live-desktop-radius.png`): "Selected: 97.9 miles", 0 / 25,000 miles bounds, numeric Min/Max fields, no price sliders. The handle at 97.9 sits near the left end of a 25,000-mile track (the usability issue F-144 addresses).
- Not tested: the owner's PIN Save (owner action). Cost: UNKNOWN.
- Verdict: **F-143 LIVE_VERIFIED at 315ddfa (executed by the owner).** F-145 (`3960e46`) remains STAGING_ACCEPTED and not live.
