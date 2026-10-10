# OWNER P0 — HOUR EXPIRED: SHIP EXISTING MARKETPLACE; NO MORE DEMO AS PRODUCT

ID: ARIA-20261009-2100-deadline-marketplace-rollout-and-future-research
Created: 2026-10-09, ~21:00 CDT, after owner's requested one-hour target
From: Michael via ChatGPT Aria, owner-side liaison
Type: URGENT_OWNER_ACCEPTANCE + FUTURE_PRODUCT_BACKLOG
Source: owner message "And the hour's up" following the previously authorized staged live-marketplace plan; latest GitHub reads named below.
Project: Deal Sniffer / Michael Business OS only.
Safety: DRY-RUN; no spend, no seller contact, bids, purchases, scraping bypass, credential/token sharing, DB delete, or changes to CAOSCare/Desktop-Agent. Keep Agent 01 coordinator, no more than 2 bounded workers and normal usage guard.

## OWNER EXPECTATION — NOW, not later

One hour has elapsed. Owner wants to see a usable **Michael's Marketplace** on the ordinary UI :8766, not an engineering report, fictitious TV/mower/ATV or more architecture. First real GSA auction and search/saved-search flow must be visible, with actual original link and truthful price, location, date, source-as-of and condition/cost unknowns. If not live, state exactly why, what step remains and who owns it.

## GitHub evidence read by owner-side Aria at message time

- Coordinator branch `research/agent-01-coordinator` HEAD last independently read: `a1fc22d35fd7891054701c4e78544a65b123b7fe` — F-46/F-47 reconciled; NO observed committed live :8766 reload proof after that.
- Specialist lane 06 `research/agent-06-communications` at `5b42655cb2cebdd318c8ad2c9729bcba09df5c2a` now lists **F-48 DONE @ `4ce0c13`**. Receipt `docs/receipts/2026-10-10-f48-landing-fixes.md`.
- Receipt confirms GET / → 303 /market; /queue retained; demo excluded from queue/mission header best-next-move; simulated $500 bankroll labelled not real cash; no broken GSA `ppms.gov` images (auth requires original listing); free-entered origin/radius UI, but **NOT all geolocations are supported yet**. Unknown city/ZIP => distance UNKNOWN and radius NOT applied; don't claim arbitrary-location filtering works universally.
- Receipt documents testing caveats: 310 pass / 1 fail order-dependent `test_resale_f39` (passes alone), 105 pass / 2 fail pre-existing F-32; `/mission` may still show demo legs. Do NOT misstate as all green. Verify exact gate pre-reload.
- Previous coordinator terminal screenshot: staging :8767 rendered real GSA results, including Marianna trailer with recorded $25 bid and original link, and queue said 'Demo data hidden (3 items)' but live :8766 was old snapshot as of 20:29 CDT; this is COORDINATOR SELF-REPORT, not owner browser acceptance.

## ONE work item now — integrate, rehearse, show owner the real screen

1. Agent 01 sync/ACK this owner note and previous acceptance messages; inspect active tasks, actual :8766 and :8767 process/runtime, workspace, head, DB and latest lane 06 F-48. Avoid interrupting an already active compatible integration.
2. Stage updated lane 06 package + verified GSA cache source in the existing UI runtime, no parallel product or new architecture; run complete applicable regressions and classify documented failures, preserve receipts.
3. Re-check with browser + real source evidence on staging :8767: root redirects to Marketplace; one genuine GSA lot with original link; no demo deals in normal main feed, normal approval queue, or best-next-move; clear demo-only bankroll; editable location/radius with truthful geocode limitations; saved search survives reload; honest photo fallback.
4. If and only if current owner's prior approved one-time UI-only reload is recorded as valid for the now-tested F-48 artifact, perform that **one** controlled ~10-second `mbos-dev-ui` service reload preserving DB, worker, dispatcher, receipts and rollback. If approval is not actually on record, ask ONE consolidated narrow approval with tests and scope; do not silently restart.
5. Verify :8766 itself with server response and browser, screenshot and receipt; owner should open ordinary http://127.0.0.1:8766/ and SEE Michael's Marketplace. Report precise route, version, source lot, source timestamp, source URL, screenshots, tests, regressions and remaining limits.
6. Never mark done on staging/branch-only evidence. If unable to roll out, report *actual blocker*, not another design request.

## AFTER the first live Marketplace is accepted — P2 parked product idea

Michael wants to send **an item he is considering buying** through **Ask Aria Messenger / the mobile interface**, including URL, photos and seller description, and ask "is this a deal?" The system should attach the real listing with provenance, optionally research comparable SOLD prices and feasible repair/transport/fees, produce evidence-based BUY/WATCH/PASS, then show an explicit **"More Research"** action on a deal card to commission deeper bounded research. Make this a single future enhancement in the existing owner-supplied intake / research flow, not a new project or UI rewrite. Scheduled inbox polling may support message receipt, but never imply ChatGPT itself is a continuously listening background agent without an actual configured task. Do NOT start this while real-source live rollout remains unaccepted.

Respect module-size review (<300 lines target; 400 review/hard stop), receipts/provenance, provider quota and operator authority. Owner expects **results now**.

## ACK required
Write `docs/messages/acks/ARIA-20261009-2100-deadline-marketplace-rollout-and-future-research.md` on coordinator branch on first manual liaison sync. ACK must name integration owner, current stage, whether live port :8766 is new or old, whether the one-time reload is authorized, and next exact test. Recording this message in GitHub does NOT prove Agent 01 received it.
