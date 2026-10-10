# ARIA LIAISON — PUBLIC GSA AUCTION API + FIXTURE-STARTUP P0

ID: ARIA-20261009-1903-public-gsa-api-and-fixture-truth
Created: 2026-10-09 ~19:03 CDT (owner continuation)
Sender: Aria, owner-side liaison
Type: PROJECT_FACT / TASK_REQUEST
Source/provenance: owner's explicit current instructions in ChatGPT; read-only coordinator branch c4b849dec78eb3911bc230acd34ff99ce5762587; official GSA Auctions API docs (URLs below); independent web terms checks.
Authority: Read-only research and ordinary bounded DRY-RUN development only. No paid services, seller contact, bids, purchases, new account or credentials, CAPTCHA/bot/ToS bypass, production deploy, or modifications to paused CAOSCare / Desktop-Agent.

## Owner intent — same P0, do not create duplicate tickets
Read the existing unacknowledged messages:
- 2026-10-09-aria-cross-chat-handoff-real-sourcing-p0.md
- 2026-10-09-aria-owner-real-listings-not-fixtures-resume-manual.md

Owner wants ACTUAL public ads and auctions + original photos/links/locations/asking or current bid + honest SOLD comps/fees/net/time and BUY/WATCH/PASS in the existing :8766 UI. No training fixtures disguised as money leads. Approximately $500/week independent income goal, near Conway AR about 100 miles. Maintain separate demo mode. Do not ask owner to research comps.

## Independently verified repo findings
- `tools/run_dev_stack.sh` starts `mbos.cli worker --fixture fixtures/sources/training_examples.json`, every START (and forcibly kills/restarts the current tmux sessions). Thus ordinary launch **always** injects training deals. Do not restart a running stack merely to prove this. A normal, deliberate LIVE mode must never have `--fixture`.
- `src/mbos/cli.py` accepts optional `--fixture`; `src/mbos/production.py` already reports "sources STAND-IN: no source adapter configured" when none exists. Preserve truth; empty live queue is better than false deals.
- B-12 live source smoke remains BLOCKED on credentials/operator access. B-23 auction adapter and A-51 valuation work were proven on fixtures, NOT current live auction data. F-45 photos/real source URL UI marked DONE in queue but no local :8766 verification from this liaison.
- Coordinator repo head `c4b849d` (2026-10-09 23:37Z) marks F-45 verified; liaison head before this message `e642e45`. These are GitHub facts, not evidence of current on-host behavior.
- Do not ignore the Owner no-title/paperwork opportunity class; document extra costs/time/risk.

## Genuine public source lead (highest value new finding)
The U.S. General Services Administration officially publishes **GSA Auctions API**, a read-only GET API for LIVE JSON/XML auction lots:
- Docs: https://gsa.github.io/auctions_api/basics
- Field reference: https://gsa.github.io/auctions_api/fields
- Dataset: https://catalog.data.gov/dataset/gsa-auctions-api
- Official sample endpoint (DEMO_KEY is rate-limited; not verified on EliteDesk):
  https://api.gsa.gov/assets/gsaauctions/v2/auctions?api_key=DEMO_KEY&format=JSON
- Documented fields include SaleNo, LotNo, AucStartDt, AucEndDt, ItemName, PropertyCity/State/Zip, AuctionStatus, BiddersCount, LotDescript, Reserve, HighBidAmount, ItemDescURL and ImageURL. **Do not invent values absent in the API** (e.g., buyer premium or sold comps).
- API docs say demo key is limited and a personal key may be requested from api.data.gov; do not apply/create an account or enable paid API without owner authorization. The docs advertise rate limits (5,000/day and 5/5s), but verify real access/response/status before calling this an enabled source.
- Source may be sparse near Conway. Filter by Arkansas / approximate distance only when geodata sufficient and present zero results truthfully.
- Source-policy caveat: Craigslist terms expressly forbid unlicensed automation for search/collection (https://www.craigslist.org/about/terms); Purple Wave terms restrict robot access (https://www.purplewave.com/auction/legal/website). Do NOT implement unsanctioned site scrapers. eBay Browse API is official for current listings but needs developer app token (https://developer.ebay.com/develop/api/buy/browse_api); eBay sold Marketplace Insights is limited release (https://developer.ebay.com/api-docs/buy/marketplace-insights/static/overview.html), so no claims of automatic sold comps until authorized/proven.

## Requested next action by Agent 01 (not a new parallel project)
1. Reconcile existing P0 inbox instructions/acks and active worker commits. Protect running tasks/quotas, max 2 bounded workers.
2. Reproduce current UI fixture leakage and ensure normal landing screen does not surface TRAIN-* as seller leads or owner approval items. Fixture catalog only in unmistakably separate DEMO/TEST mode. Don't kill running services without owner approval.
3. Assign existing lane 02 a bounded zero-paid-API feasibility/smoke of the official GSA Auctions API DEMO_KEY, with 1 read-only request (under posted limits) if policy allows. Report actual HTTP status, time, response shape, sample authentic lot IDs/original URLs/images or exact blocker. If DEMO_KEY unavailable, report need for owner-provided free api.data.gov key (one consolidated request), not imaginary live data.
4. Connect permitted real records to the existing B-23→A-51→F-45 path, preserving original source URLs, listing photos, exact seller/agency wording, as-of timestamps, bid/date/location evidence. No fake SOLD comps: asking-only is not sold proof. Put incomplete valuation in WATCH/RESEARCH, never confident BUY.
5. In parallel, implement an **owner-supplied genuine URL/photo/text import** into the same existing UI, only for information the owner is permitted to share/use, with origin marked OWNER-SUPPLIED, review and provenance; no bulk copying restricted listings. This is interim, NOT a substitute for automatic lawful discovery.
6. Stage acceptance: one genuinely current verified auction/listing rendered in :8766 with original link and photo where allowed, provenance and truthful costs/UNKNOWN; screenshot; no fixture in normal feed; tests/commit/receipt; the exact blocked provider dependency if no records exist.
7. ACK this message in `docs/messages/acks/ARIA-20261009-1903-public-gsa-api-and-fixture-truth.md` on coordinator branch. Process previous two owner P0 messages in the same reconciliation to avoid duplicate work.

This GitHub note is an owner liaison deliverable; NOT approval to deploy or to spend. CAOSCare paused, Room 214 must stay unchanged; Desktop-Agent paused/offline. Do not restart either.

Core law: No action without a receipt. No receipt without provenance.
