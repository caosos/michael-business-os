# OWNER P0 — MICHAEL'S MARKETPLACE — ONE-HOUR VERTICAL SLICE

ID: ARIA-20261009-1920-michaels-marketplace-one-hour-vertical-slice
Created: 2026-10-09, Friday evening CDT
Sender: Owner via Aria (ChatGPT owner-side liaison)
Type: OWNER_INPUT / TASK_REQUEST
Authority: existing DRY-RUN development only. No paid calls/services, scraping that violates terms, bypass, seller contact, bidding, purchase, deploy to other projects, destructive data reset, or restarts of paused CAOSCare/Desktop-Agent.

## Exact owner direction

**"I want Michael's Marketplace. Look like this ChatGPT screen: left sidebar with saved searches/campaigns and options, main pane browsing actual marketplace and auctions. I enter the item, distance, maximum price, condition, and required/optional characteristics; search descriptions and return original photos/listings. Start with ONE REAL auction, then another source, then another. I want something usable within an hour, not another plan or fake training queue. STRICT CONTROL of agents; NO GOD FILES >300–400 lines. I want to know what they are doing."**

The money-hunt product is a marketplace aggregator/research tool, NOT primarily an accounting or developer control UI. UI experience should feel like browsing Facebook Marketplace but aggregate permitted source listings and auctions. Editable filters/campaigns are front and center, technical tables collapsed. Saved campaigns are actual persisted queries, not a promise that a disconnected source is being monitored.

## Freshly reconciled facts (read-only, 2026-10-09 ~19:xx CDT)

- Coordinator branch HEAD observed: c2373f3f83fc5f188682eb9937a98590e2779b9.
- Existing GitHub ACKs now CONFIRM all three prior real-source directives processed; official GSA Auctions DEMO_KEY smoke reports HTTP 200, 1,179 active lots, 19 Arkansas, including a Marianna utility trailer. Receipt: docs/receipts/2026-10-09-gsa-api-smoke.md. This is the strongest lawful initial source.
- Existing READY tasks B-25 (lane 02 GSA live adapter) and F-46 (lane 06 separate demo from live and owner URL intake). Existing F-45 rich gallery and filters marked DONE, but not accepted on real :8766 browser.
- `tools/run_dev_stack.sh` on coordinator branch FIXED to omit `--fixture` by default. Demo only via MBOS_DEMO=1. **Old TRAIN-* records remain in existing DB**; F-46 must hide them from default live queue without destructive deletion or requiring UI server restart during unapproved downtime.
- Work remains subject to 90% Claude usage guard, max two heavy bounded workers. Owner reported a free usage reset, but coordinator must query current meters rather than trust an older screenshot.
- CAOSCare paused, Room 214 unchanged. Desktop-Agent paused, :8477 service and relay remain offline. Do NOT restart either.

## Deliverable: within ~60 minutes of Agent 01 receipt, get ONE vertical slice on existing :8766

Use the existing code, components, schema and UI. Do not redesign architecture. Do not spin up all seven sessions. Agent 01 owns integration; bounded lane 02 discovery and lane 06 operator UI work with non-overlapping files.

**Visual structure / first screen:**
- Persistent left sidebar like ChatGPT: **Find Deals Now**, **+ New Search**, **My Campaigns / Saved Searches**, **Saved Deals**, **Auctions Closing Soon**, optionally DEMO in a clearly separate area. Search name can be e.g. 'Utility trailers'. Main pane title **Michael's Marketplace**.
- An easy search form: what item/keywords/category, base city (Conway AR default user-editable), radius miles, max cash/price, condition (running / nonrunning / parts / salvage / any), required vs preferred descriptors from seller text (e.g., 'tandem axle', 'no title', 'needs engine'), exclude terms, source selection (GSA first), auction/fixed price, closing date and sort. All fields optional with defaults; keyword + price + radius enough to create. NO global hardcoded tow exclusions. Show which fields were NOT supplied by source rather than manufacturing them.
- Save, edit, enable/disable, run saved campaign. Use existing Wanted/campaign models and saved filters where they exist; no parallel datastore. A newly saved search persists across page reload. Search uses genuine retrieved records and visibly displays connected/offline/last fetched as-of info. If a source is unsupported, show not connected, NOT mock results.
- Real result card: original seller/government photo gallery if provided, exact source title and short original description, original listing URL, actual price/current bid, closing date, city/distance ONLY when grounded, condition *seller-says*, title status if stated, source + fetched timestamp. CTA 'View original listing'. Per-card price math: bid + buyer premium/tax/transport + repair (UNKNOWN until evidence) -> all-in and plausible net; SOLD comparable evidence distinct from asking; default WATCH/RESEARCH NEEDED for insufficient valuation. Never present a price/condition/comp or photo not in provenance. Do not show BUY if evidence insufficient.
- Absolutely NO TRAIN-* / example.invalid in normal LIVE results or owner decision queue. Distinct opt-in DEMO route/filter with large 'NOT REAL ADS — TRAINING DATA' indicator; never clickable fake source. Distinguish fictional $500 ledger from actual owner cash.
- The user should be able to create a saved query, press Find Deals Now and see the actual GSA result(s), click a REAL original link, and return without visiting many websites just to browse.

**Order, with intermediate visible check after each:**
0. Agent 01 sync liaison inbox and ACK; inspect actual tmux processes, DB, running UI, agent assignments and uncommitted changes (DO NOT kill/restart running services). Publish 5-line progress (owned files, tasks, head, current blocker, next).
1. Source, Lane 02 B-25: one cached, permitted official GSA API fetch, normalize authentic lots with real URL/image/price/date/location and original wording; confirm at least one identified live lot & as-of proof. Do not rely only on its fixture adapter tests. If requested auction lot expired / no local results, truthfully show actual permitted results/zero. Use official GSA API terms/limits. Do not fabricate comp prices or fees.
2. Truth/UI, Lane 06 F-46: filter training records from normal browsing and decision lists using canonical source classification; do not delete DB. Keep DEMO opt-in; do not show training approvals.
3. Reuse existing F-45 UI + Wanted campaigns to build simple left sidebar, create/edit/save/run filter campaign (ONLY approved source). Model parsing from ad description with seller-stated vs inference tags. Do not create separate frontend or routes without necessity.
4. Coordinator integration in a bounded branch with tests (source payload normalization and link preservation, search/save/reload, filtering, demo isolation, lack-of-photo and stale listing, HTML escaping, ungrounded-comp WATCH); validate visually in REAL :8766 at desktop and 390px if host access exists.
5. Show Michael the working screen before polishing anything. Deliver screenshot of real listing and a short receipt (source lot ID, source URL, timestamp, branch/commit, tests, actual runtime proof). If no lawful source works, show exact blocker and implement functioning owner URL/photo/text intake instead; do NOT fake live success.

**Deadline and reality rule:** target first actual demonstrable slice within one hour from receipt, prioritize a tiny honest vertical slice over a large unaccepted redesign. Report after ~15 min meaningful milestones / blockers; NO fake promise that it is already implemented. If clock budget runs out, show working result or precise blocker and keep durable checkpoint. Do not overrun model costs/time to hide failure.

## STRICT owner agent governance (new acceptance requirement)
- Agent 01 sole coordinator. Maximum 2 bounded specialist workers as presently authorized. No unqueued task / duplicate edit scope; worker must log task ID, planned files and concrete acceptance BEFORE editing. Coordinator publishes status in human language after every stage; owner can stop next work. No costly unattended model loops, quota bypass or unrelated refactor.
- **No god files.** All NEW implementation modules/components/tests target <=300 lines; hard stop/review if >400 lines. When touching existing large files, keep change as small composition boundary or extract a contained module; do not casually rewrite existing giant files. Surface any existing >400-line file encountered and justify any exception in writing BEFORE growing it.
- Prioritize SOL/Sonnet-class ordinary coding, cheaper suitable model for extraction, stronger models only on evidence of failure. Track actual model, usage, costs as metered vs estimate, outcome and retries. Stop if resource limits real.
- Retain all receipts and provenance: real field, source URL, captured-as-of, actor, transformation, test and output.
- No silent deploy, host privilege changes, new paid API, external seller actions, bid or purchase. Owner UX acceptance on existing :8766 remains the milestone; ask consent before materially risky running-service changes.

## Source expansion AFTER FIRST REAL AUCTION WORKS
Then add each next permitted source one-by-one: Arkansas state surplus on GovDeals, PublicSurplus, local auctioneer platforms, HiBid and national equipment sites where sanctioned API/feed/license exists; ordinary FB Marketplace/Craigslist are relevant products but access restrictions require approval or user supplied links, not ToS-adverse automated scraping. Site domains and terms are tracked per adapter. Never claim 'all sources' while only one works.

## ACK required
Agent 01 writes `docs/messages/acks/ARIA-20261009-1920-michaels-marketplace-one-hour-vertical-slice.md` after processing, includes task ownership, first actual lot proof, release gate and what appears in real :8766, or exact blocker. This is an OWNER product-direction intake, not authority to rewrite every lane or disregard quota.

No action without a receipt. No receipt without provenance.
