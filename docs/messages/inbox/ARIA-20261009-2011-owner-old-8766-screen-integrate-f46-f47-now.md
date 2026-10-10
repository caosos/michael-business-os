# P0 OWNER ACCEPTANCE FAILURE — :8766 STILL THE OLD FIXTURE QUEUE, INTEGRATE EXISTING F-46/F-47

ID: ARIA-20261009-2011-owner-old-8766-screen-integrate-f46-f47-now
Date: 2026-10-09 20:11 CDT approximately
Sender: Aria, with direct owner screenshot evidence
Type: OWNER_INPUT / UI_ACCEPTANCE_FAILURE
Authority: report and bounded DRY-RUN integration/testing; no unapproved destructive DB change, paid tool, seller contact, bid, purchase, other project restart or production deployment.

## Owner evidence — screenshot at about 20:08 CDT

Michael opened actual local Chrome `http://127.0.0.1:8766/`. It is STILL titled 'Operator UI' with old top horizontal nav, and presents fictional TRAIN-* fixture:
- 'Needs from you' riding mower $480, Honda Recon $300 and demo drywall lead, each asking for a comparable SOLD price / more evidence;
- 'Needs your decision' fictitious '55 inch LED TV, works great, $30 firm, today only' with 'System says YES', contact-seller proposal and 47.5-hour approval;
- 'Cash $500 available to deploy' as though real;
- No Michael's Marketplace left sidebar, GSA auction cards or genuine listing photos.

This FAILS owner's live-screen acceptance. It is NOT resolved by F-46/F-47 passing branch tests. Do not request approval of these false training proposals.

## Source-side proof of why it is likely stale

- Latest verified coordinator HEAD as seen from GitHub at time of screenshot: `966387e8af2dea299d19500217542b5305f33119` (2026-10-10T00:24:16Z) only states 'F-47 source wiring (GSA cache path, adapter installed in lane 06 venv)'.
- Lane 06 `research/agent-06-communications` has **F-46 DONE commit `088d9fc`**, receipt `docs/receipts/2026-10-09-f46-live-vs-demo.md` and **F-47 DONE commit `4e16022`**, receipt `docs/receipts/2026-10-10-f47-marketplace.md`.
- F-47 added `operator_ui/market_search.py`, `market_view.py`, `market_routes.py`, route `GET/POST /market`, using GSA cached data and Wanted campaigns. F-46 filters fixtures out of normal queue, hides demo, prevents example.invalid links.
- F-47 receipt says 304 passing reference tests in groups, **105 pass / 2 fail pre-existing F-32 stored-input tests** on lane D+E. These failures must be classified honestly; no 'all gates green' claim without running.
- Photos did not load in F-47 headless screenshot, so do not claim real card photo acceptance yet.
- Repo coordinator root lacks `operator_ui/` directory (UI is installed lane-06 package in a venv). Worker source code on lane-06 branch is NOT proof that the active :8766 process imports it.
- `tools/run_dev_stack.sh` was changed to disable default fixture injection, but persistent old TRAIN-* database rows are untouched and the old loaded UI still shows them; avoid mass deletion.

## Immediate coordinator action — prioritize finishing integration over more feature coding

0. Sync liaison inbox, ACK this and the prior owner 'custom origin + arbitrary miles' addendum; preserve live process, local uncommitted work, evidence, ongoing tasks.
1. For running :8766: record PID/executable/module imported, package source path+version / installed venv lane 06 revision, app revision/HEAD, :8766 process start time, and whether `GET /market` returns 200 or 404. Distinguish code not integrated vs process not reloaded vs stale DB.
2. Reconcile F-46 + F-47 lane 06 to the installed coordinator UI via project approved `tools/sync_lanes.py` / venv process, preserving split owner vs worker DB credentials. Re-run F-46/F-47 reference regressions and integration smoke, classify 2 known lane D+E test failures; don't rewrite other lanes. Use one independent verifier.
3. Do **not** blindly run `tools/run_dev_stack.sh start`: it force kills both running dev tmux services. Stage/rehearse the replacement, verify health and data before an authorized brief :8766 reload, and request minimal owner approval if needed; no DB resets.
4. Check actual /market sidebar + one original genuine GSA auction lot with real link, price/bid, as-of, original photo if available; normal `/` no training NEEDS FROM YOU/APPROVAL; separate DEMO; saved campaign persists; arbitrary user-entered radius and origin (not only presets); screenshot at :8766 and receipt.
5. If :8766 screen remains old, do NOT mark DONE. Show exact blocker, task owner, ETA or step; never present unsupported claims. If /market is active but / is old, owner needs discoverable Marketplace as default landing route or obvious first navigation.
6. Avoid god files: existing `operator_ui/server.py` is ~1523 lines, `backend.py` 500, no significant growth. Compose small modules <=300 new lines, 400 hard review.
7. One brief owner report: **LIVE UI VERSION**, **REAL LISTING PROOF**, **DEMO REMOVED FROM LIVE**, **TEST/RECEIPT**, **BLOCKER/NEXT**.

Owner words: 'Why does it still look like this junk?' The answer is not a new UI mockup. It is finishing and showing the existing F-46/F-47 on the ACTUAL port 8766.

No action without receipt; no receipt without provenance. Desktop-Agent and CAOSCare remain separately governed; do not touch them.
