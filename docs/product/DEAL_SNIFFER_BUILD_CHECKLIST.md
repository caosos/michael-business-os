# Deal Sniffer — Living Product Build Checklist
Updated: 2026-10-10 (owner direction). Planning baseline; NOT a release approval or worker dispatch.
Canonical owner intent: [DEAL_SNIFFER_START_HERE.md](DEAL_SNIFFER_START_HERE.md). Existing execution queue: [READY_QUEUE.md](../status/READY_QUEUE.md).
**Do not mark a feature DONE solely from an agent claim.** Track IMPLEMENTED, TESTED, STAGING_ACCEPTED, LIVE_VERIFIED separately. Existing owner pause on new assignments and releases remains in effect until superseded explicitly.

## Phase 1 — Core architecture and governance
- [x] Seven specialist lanes, coordinator queue, receipts and provenance infrastructure — built (historical implementation; current operational liveness NOT VERIFIED).
- [x] Dry-run approval/governance and state ledger implemented (prior release gate evidence).
- [ ] End-to-end task status, durable DONE history, dispatch deduplication and notification reliability independently revalidated (A-59 partial; prior duplicate F-61/F-136 dispatch).

## Phase 2 — Discovery and economics foundation
- [x] GSA read-only discovery adapter and cached real inventory (B-25; only verified connected Marketplace source).
- [x] Auction economics, buyer premium, transport, profit and maximum-bid logic implemented (C-32/C-33, A-51).
- [ ] Integrate and verify additional *local* sources: regional Arkansas auctioneers, HiBid, GovDeals, Public Surplus, Craigslist; evaluate Facebook Marketplace and OfferUp supported discovery or owner-assisted import. Do not claim APIs exist without evidence.
- [ ] Source coverage and freshness per source; distinguish no matches from source not searched; avoid false fresh/live claims.
- [ ] Real-source deduplication, price-change and closing alerts with verified provenance.

## Phase 3 — Marketplace usability (ACTIVE)
- [x] Marketplace live on local :8766 with real GSA cached listings, strict location/state/distance and price filters (A-58 receipt).
- [x] A-60 red X, stable-ID hide, hidden-items list, individual undo, persistence, learning separate: Agent 06 implementation + staging receipt at 4a818b97; **do not treat as live acceptance without owner interaction**.
- [ ] Reconcile existing independent A-60 review and record final owner live Hide/Undo acceptance (do not duplicate review or worker).
- [ ] Move Search Now to **bottom of all search filters**: location, radius/state, price, category, condition, keywords, advanced; owner screenshot 2026-10-10.
- [ ] Simplify New Search / Save Search / Saved Searches labels, spacing and visual hierarchy; show useful inventory first.
- [ ] Verify saved search, PIN and preferences persist across restart without retrieving/publishing PIN.
- [ ] Gallery/list real photographs, original descriptions/links, source, distance, freshness, and honest unknowns; responsive desktop/mobile.
- [ ] Ensure red X never alters learning weights or saved owner bid/watch obligations.
- [ ] Accurate opening/next minimum auction bid when verifiable, otherwise UNKNOWN plus original link (A-62 waits behind A-60).
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
- [ ] Private decision cases: A-61/A-64 code exists; owner-local import/readback and similarity proposal NOT VERIFIED; never publish private financial values.
- [ ] Reliable builder completion/blocked notifications and next eligible task recommendation, without duplicate workers or autonomous external actions.

## Phase 6 — Repeatable product and onboarding
- [ ] Simple conversational onboarding for region, skills, capital, constraints and sources.
- [ ] Multiple independent operator profiles with isolation, receipts, backup/restore and documented support.
- [ ] Reproducible deployment and end-to-end acceptance for an additional operator.

## Current build control / owner-facing reporting contract
- Current phase: 3/6, Marketplace usability. Phase percentage: NOT MEASURED until acceptance cases mapped.
- Current completed code: A-60 source afe269da; staging tool a9be4e4; receipt 4a818b97. Latest prior report says live release; owner Hide/Undo acceptance still pending.
- Next engineering candidate: A-62 (bid accuracy) after A-60 review/acceptance and explicit resume of assignments.
- Current blockers: insufficient live local sources, stale GSA cache, UI filter placement, owner pause on new assignments/releases.
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
- Current five-minute idle enforcement: NOT VERIFIED. Current direct cloud push notification to this chat: NOT VERIFIED. Current local worker liveness: NOT VERIFIED from GitHub alone.
