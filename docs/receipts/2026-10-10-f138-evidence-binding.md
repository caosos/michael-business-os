# F-138 final source-to-evidence binding (evidence only; F-137 not reimplemented)
- Code SHA: eda3eee6d303ab6ee1df419b66d54c831d7d8b1d, clean checkout (`git status` empty before run; UI/tests/tools identical to d537b27, only AGENT_STATUS differs). Evidence JSON: `dirty:false`.
- Script: existing `tools/f137_browser.py`, run once, unchanged. Captured 2026-10-10T19:05:07Z (UTC; `captured_utc` added to the JSON after the run, nothing else edited).
- Isolated staging only: stub store, COPY of the GSA cache, loopback 127.0.0.1 (random ports), test PIN. No :8766 reload, fetch, billing or access change.
- Cache sha256 d02f3acc4a6eef4b7abd4065c2dc5d4370dd6064fe0bba1b385ec6a8fa154ba7, as-of 2026-10-10T00:19:23.772932+00:00.
- Viewports desktop 1648x1000, mobile 390x844; scrollY=0 on load for all six shots (label shots then scrolled to the label, recorded as scrollY_after).
- Real Chrome Save click, reopen, then real process kill and restart: PIDs 3993613 -> 3994028. Controls (State mode, AR+TX, also-radius) and lot ids identical before save, after reopen, after restart.
- Tests (focused only): f61+f137+f136 = 33 passed / 0 failed. No full-suite repeat.
- Verdict: PASS. Supersedes the 1182e8a dirty:true evidence. Gates a separate owner live-approval request; this task does not request or perform it.
