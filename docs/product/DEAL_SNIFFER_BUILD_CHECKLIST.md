# Deal Sniffer — Living Product Build Checklist
Updated: 2026-10-11 06:17 CDT (evidence reconciliation). Planning baseline; NOT a release approval or worker dispatch.
Canonical owner intent: [DEAL_SNIFFER_START_HERE.md](DEAL_SNIFFER_START_HERE.md). Existing execution queue: [READY_QUEUE.md](../status/READY_QUEUE.md).
**Do not mark a feature DONE solely from an agent claim.** Track IMPLEMENTED, TESTED, STAGING_ACCEPTED, LIVE_VERIFIED separately. The earlier 05:28Z compute pause was explicitly cancelled at 05:30Z; ordinary no-extra-cost development is authorized by newer owner direction, but each live release retains its own gate. This status document does not dispatch work.

## Phase 1 — Core architecture and governance
- [x] Seven specialist lanes, coordinator queue, receipts and provenance infrastructure — built (historical implementation; current operational liveness NOT VERIFIED).
- [x] Dry-run approval/governance and state ledger implemented (prior release gate evidence).
- [ ] End-to-end task status, durable DONE history, dispatch deduplication and notification reliability independently revalidated (A-59 partial; prior duplicate F-61/F-136 dispatch).

## Phase 2 — Discovery and economics foundation
- [x] GSA read-only discovery adapter and cached real inventory (B-25; only verified connected Marketplace source).
- [x] Auction economics, buyer premium, transport, profit and maximum-bid logic implemented (C-32/C-33, A-51).
- [ ] Integrate and verify additional *connected local* sources. Verified status: GSA is the only connected read-only source. F-141 Facebook/Craigslist/OfferUp “Your finds” is manual owner entry and does **not** count as discovery. B-06 has fixture-tested alert-email parsers for GovDeals/PublicSurplus/EstateSales.NET; B-23 has fixture-only GovDeals/PublicSurplus/HiBid auction adapters. None is live-activated. Facebook unattended fetch/scrape is forbidden by current policy; Craigslist and the B-23 sources remain disabled pending existing B-12 owner source approval and operator credentials. Use existing B-12 for the next source path—start with the already-built GovDeals/PublicSurplus alert-email route; do not create a duplicate task or claim an API without evidence.
- [ ] Source coverage and freshness per source; distinguish no matches from source not searched; avoid false fresh/live claims.
- [ ] Real-source deduplication, price-change and closing alerts with verified provenance.

## Phase 3 — Marketplace usability (ACTIVE)
- [x] Marketplace live on local :8766 with real GSA cached listings, strict location/state/distance and price filters (A-58 receipt).
- [x] A-60 IMPLEMENTED / TESTED / STAGING_ACCEPTED: Agent 06 code afe269d; 9 focused tests passed; actual Chrome mouse/keyboard interaction, restart, undo and mobile/desktop screenshots on isolated staging (receipt 4a818b9 and `docs/receipts/2026-10-10-a60-hide-listing.md` on lane 06). Existing reviewer/owner-facing approval for the exact bounded artifact is recorded in liaison `ARYA-20261011-0137-owner-approved-a60-release.md`. No duplicate review needed.
- [ ] A-60 LIVE_INTERACTION_ACCEPTED: bounded UI-only release :8766 was recorded at 2026-10-11T01:40:58Z (artifact a9be4e4, disk hash + restart + functional checks, original GSA cache, desktop/mobile screenshots; `docs/receipts/2026-10-11-live-8766-reload-a60.md`). Live X controls were observed, but live Hide/Undo on real owner preferences was deliberately NOT exercised. Wait for normal complete-section owner review; do not repeat staging independent review or release.
- [ ] Move Search Now to **bottom of all search filters**: location, radius/state, price, category, condition, keywords, advanced; owner screenshot 2026-10-10.
- [ ] Simplify New Search / Save Search / Saved Searches labels, spacing and visual hierarchy; show useful inventory first.
- [ ] Verify saved search, PIN and preferences persist across restart without retrieving/publishing PIN.
- [ ] Gallery/list real photographs, original descriptions/links, source, distance, freshness, and honest unknowns; responsive desktop/mobile.
- [ ] Ensure red X never alters learning weights or saved owner bid/watch obligations.
- [x] A-62 IMPLEMENTED / TESTED / LIVE_VERIFIED (read-only): when no source minimum exists, cards show “Opening/minimum bid unknown” plus the original link and never invent a number; an explicit positive source minimum is shown only with provenance. Lane 06 `cc16e62`; 4 focused tests; released as artifact `0cb8459` to :8766 at 2026-10-11T04:21:13Z with GET/browser screenshot evidence (`docs/receipts/2026-10-11-live-8766-reload-f139-f140-a62.md`). Owner-state Save and Hide/Undo clicks were not exercised.
- [x] F-141 IMPLEMENTED / TESTED / LIVE_VERIFIED (read-only): “Add a find” accepts owner-entered Facebook Marketplace, Craigslist, OfferUp or other links without fetching/scraping them; keeps “Your finds” separate from GSA; persists locally; rejects duplicates; honors strict filters and existing Hide/Save controls. Lane 06 `471be60`; 13 focused tests; staging add/persist/restart/filter/mobile evidence; released as artifact `63d741d` to :8766 at 2026-10-11T04:52:41Z (`docs/receipts/2026-10-11-live-8766-reload-f141.md`). The live form and empty section were verified without writing Michael’s file; OWNER_ACCEPTED add/edit/delete/undo remains pending.
- [ ] No synthetic listings, fabricated replacements, hidden-out-of-filter substitutions, or silent zero-result misrepresentation.

## Phase 4 — Real local deal intelligence and end-to-end acceptance
- [ ] Unified local trailer/equipment searches within owner-configured radius (50 preferred; 100+ only if worthwhile).
- [ ] Actual listing-photo inspection before confident trailer recommendation: frame, tongue, axles, suspension, wheels, floor, coupler, wiring; separate visual facts, seller claims, UNKNOWN.
- [ ] No-title / paperwork-discount paths with provenance, Arkansas cost and timing; never reject categorically.
- [ ] Compare whole resale vs repair/resale vs part-out vs repurpose vs scrap as *alternatives*, never sum mutually exclusive proceeds.
- [ ] Real sold-price evidence where available; conservative/likely/optimistic resale, all-in costs, profit/hour, capital velocity, max bid and uncertainty.
- [ ] Independent acceptance using real sourced local opportunity, no fake $30 television as sole proof.

## Phase 5 — Daily operations and cash conversion
- [ ] Morning Money Hunt with verified real opportunities, source freshness and meaningful alerts.
- [ ] Owner-reported bids and obligations, reserved capital, protected principal, deployed capital, available capital; no double use of funds.
- [ ] Intake owned asset photos, repair plan, materials, time, expenses, resale listing preparation, buyer/offers, actual sale and realized profit.
- [ ] Private decision cases: A-61/A-64/A-67 code and owner-local import/readback/hash verification recorded in coordinator receipts (36d6eab/fee0803, 2026-10-11T02:01Z); F-139 read-only card display + F-140 store-path correction IMPLEMENTED/TESTED (8+5 focused tests, 128f6c8/29fbf0e) and released as artifact `0cb8459` to :8766 at 2026-10-11T04:21:13Z. The live code path resolved the real owner-local store and rendered a matching synthetic/live-layout proof with estimates labelled, but the current live cache has no matching card, so owner-visible live-card acceptance remains open. No private decision values were published.
- [ ] Reliable builder completion/blocked notifications and next eligible task recommendation, without duplicate workers or autonomous external actions.

## Phase 6 — Repeatable product and onboarding
- [ ] Simple conversational onboarding for region, skills, capital, constraints and sources.
- [ ] Multiple independent operator profiles with isolation, receipts, backup/restore and documented support.
- [ ] Reproducible deployment and end-to-end acceptance for an additional operator.

## Current build control / owner-facing reporting contract
- Current phase: 3/6, Marketplace usability. Phase percentage: NOT MEASURED until acceptance cases mapped.
- Verified A-60: source afe269d / staging a9be4e4 / receipt 4a818b9; STAGING_ACCEPTED and bounded :8766 reload recorded at 01:40:58Z on October 11 UTC. Live X controls confirmed visible; owner-data Hide/Undo interactions and whole Marketplace section acceptance remain unverified.
- Reconciled: F-140 is DONE @ `29fbf0e`; A-62 is DONE @ `cc16e62`; both were released with F-139 as artifact `0cb8459`. F-141 owner-entered finds is DONE @ `471be60` and released as artifact `63d741d`. A-69 continuity is DONE @ `7aaed3e`: 17 tests, three expiry/re-arm cycles, one watcher at a time, maximum observed gap 6.42 seconds. A-68 remains PARTIAL because a genuine completion-to-next-eligible-task transition has not yet been measured.
- Current blockers/gaps: direct connected local sources and Search Now/filter placement remain product gaps; F-141 is a manual bridge only. Existing B-12 live-source activation is blocked on a source-specific owner decision plus operator credentials/access; the chosen first compliant path is the already-built GovDeals/PublicSurplus alert-email ingestion, not scraping. GSA cache refresh recorded at 2026-10-11T02:48:28Z (1167 records; commit `143aeed`); inventory may age again. A-69 proves feed re-arm continuity only while the interactive session stays open; A-68 completion-to-next-task remains PARTIAL. Reboot persistence is NOT installed: at 2026-10-11T07:54:52Z the host had no MBOS user units, and the permission classifier refused the install. Genuine owner action required: type “install the user-level MBOS persistence units” in the existing Agent 01 session or add the documented narrow Bash permission. Do not infer current process liveness from that older receipt.
- For each task record: owner requirement, task ID, lane, priority, dependency, implementation SHA, test receipt, staging browser proof, live acceptance, last updated, blocker, next action, ETA confidence.
- Never guess ETA or percentages. Publish estimates only with scope, dependencies, and evidence.
- On every meaningful task completion: update this checklist AND queue atomically where authorized, preserve historical DONE entries, link receipt, and notify only for actionable change.
- Governance: no bids, purchases, seller contact, provider/account changes, spend, service changes or deployment from this checklist.

## Owner operating directive — 2026-10-10 22:07 CDT
- Deal Sniffer supervisor owns communications and the authoritative phase/checklist reporting; do not conflate docs ACK with engineering START or completion.
- Goal: no eligible authorized build task left idle more than five minutes after prior task completion. Implement five-minute *local* coordinator/watchdog detection and next-task recommendation/dispatch through the existing permitted path, with receipts; ChatGPT's hourly monitor alone cannot enforce this SLA. No new competing coordinator, process, or scheduler.
- Builder completion must publish GitHub receipt with task ID, commit SHA, tests, browser screenshots where applicable, queue status, and next eligible task. Coordinator must update this checklist and queue without losing historical DONE rows.
- Notify owner only for finished sections needing acceptance or genuine authority/permission blockers; preserve live release gates and no-spend/no-bid restrictions.
- Any user-facing change requires actual browser interaction (desktop and mobile), not only code tests. Target source modules under 400 lines when practical; split by responsibility, avoid artificial fragmentation.
- ~~SUPERSEDED by the coordinator reconciliation below (2026-10-11, A-68)~~ Five-minute idle enforcement: NOT IMPLEMENTED in the inspected source snapshot (see source-audit receipt); current local worker liveness and direct cloud push notification to this chat remain NOT VERIFIED.


## Supervisor verification — five-minute detection and handoff (2026-10-11)
- Source-audit receipt: [2026-10-11-supervisor-five-minute-check.md](../receipts/2026-10-11-supervisor-five-minute-check.md), inspected at `336a4ff`.
- ~~SUPERSEDED by the coordinator reconciliation below (2026-10-11, A-68)~~ Five-minute idle detection: **NOT IMPLEMENTED in the inspected source**. `foreman.py` reports state but does not time or dispatch; `coordinator_watch.py` polls every 120 seconds, uses a 900-second stale threshold, and rate-limits wakes to 600 seconds. `dispatcher.py` polls every 90 seconds, but its source does not enforce a five-minute maximum idle interval.
- Next-task handoff: source supports recommendation/notification only. `engineering_session.finish` records the next task and makes it announceable on the next feed cycle; the interactive session must begin it. `next_work.py` polls at least every 120 seconds, reminders are 600 seconds apart, and each Monitor expires after 30 minutes unless the session re-arms it. Historical focused tests and Monitor receipts do not prove a current live run.
- ~~SUPERSEDED by the coordinator reconciliation below (2026-10-11, A-68)~~ Current local liveness and end-to-end handoff: **UNVERIFIED**. This Work session could not connect to `:8766` and has no local checkout/process view. Do not report the five-minute requirement as working.
- Coordinator reconciliation recorded F-140 DONE @ 29fbf0e and A-62 BLOCKED → READY after A-60 DONE. A-68 is READY for the five-minute SLA repair, followed by A-62. Neither was claimed or started in this session; no duplicate worker or monitor created.


## Coordinator reconciliation (Agent 01, A-68, 2026-10-11)
- **Code/tests:** five-minute handoff IS implemented in the existing path: `tools/next_work.py` (poll 120 s, cap 240 s, announce at once, unclaimed re-announced every 300 s, pause/quota/claim/DONE/unmet-dependency suppression, latency log `var/next_work_log.jsonl`) with `tools/engineering_session.py` (idempotent claim/finish, next task announced on completion). Fake-clock tests (299 s quiet / 300 s reminder, once-only, suppression, restart recovery): 16 next_work + engineering_session tests pass. Commit a838b5d.
- **Live proof:** one real instruction handoff observed, publish to notification 32.5 s (<= 300 s); receipt [2026-10-11-a68-runtime-proof.md](../receipts/2026-10-11-a68-runtime-proof.md). Still UNPROVEN: steady-state poll latency (the sample included a fresh watcher start) and the completion-to-next-task handoff (no eligible next task existed). A-68 stays PARTIAL.
- **Limits:** session-open lifetime; Monitor expires every 30 minutes and is re-armed by the session (nothing is delivered in the gap). `coordinator_watch.py` was not changed (its 600 s dispatcher restart guard is outside the handoff path).
- **Continuation result / next action:** A-69 is DONE @ `7aaed3e` with 17 tests and three live expiry/re-arm cycles (max gap 6.42 seconds, duplicate watcher suppressed; `docs/receipts/2026-10-11-a69-a70-continuity.md`). F-141 was released successfully to :8766 as artifact `63d741d` at 2026-10-11T04:52:41Z with no rollback. Next: owner acceptance of the finished “Add a find” section, and separately capture a genuine completion-to-next-eligible-task transition for A-68. Reboot persistence remains blocked on the narrow typed permission documented in `docs/receipts/2026-10-11-reboot-recovery-closeout.md`; do not create another service or monitor.
