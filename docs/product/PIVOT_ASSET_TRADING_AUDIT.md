# Pivot audit: asset acquisition, auction intelligence and resale (not labor)

Directive: Michael, in-session, 2026-10-09 ("Deal Sniffer is an asset acquisition, valuation, auction intelligence, and resale platform. It is NOT a labor lead-generation platform."). Audit by Agent 01 from the pushed heads of the lane branches (FACT = read from the code or docs; INFER = my reading; UNK = not checked). Nothing was deleted, changed or run live.

## 1. Labor-oriented components found (preserved, not removed)
| Where | What | Labor-only? |
|---|---|---|
| Lane 02 `adapters/service_intake.py`, `campaigns.py` (`lane = "service"` for mobile_repair, drywall_repair, assembly, handyman, smart_home_install and similar) | service-lead intake and campaign routing | yes |
| Lane 03 `lanes.py`, `estimate.py`, `inputs.py` (C-25 scope/customer attestation, C-27 scope override, C-28 `quote:amount_usd`), `economics/tests/test_c28_service_quote.py`, service-job schema | service-job economics: quote, hours, skills, profit per hour | yes (the per-hour math is also used for flips; keep it) |
| Lane 06 `inputs_view.py` ("Set my quote", "Tell me about the job"), `intake_view.py` | owner forms for service leads | yes |
| Lane 01 `config/intake/home_repair_job.v1.json`, intake of service leads; `mission.py` legs for service | service intake spec and mission legs | partly |
| Frozen contracts `item-service-drywall.example.json`, `service-job.schema.json` | frozen examples and schema | frozen: untouched (ADR needed to change) |
| Queue rows C-31 (reader for the quote shape) | labor-only | yes |
| A-49, D-32, F-37, F-38 | generic (HOLD to YES, schema conformance of human inputs, wake, glanceable UI) | no, keep |

## 2. What already exists for the new model (FACT)
- Sources: GSA Auctions API adapter (read-only), GovDeals / PublicSurplus / EstateSales.NET alert e-mails (B-06, read-only IMAP), eBay Browse and Insights (credentials pending, B-12), Trash Nothing, SAM.gov. Dedup and photo hashing done (B-10, B-11).
- Economics: buyer premium % is already added to buy fees (`estimate.py`), `auction_current` and `starting_bid` price types, auction-ends-in-hours as a timing input, engine `walk_away_price` is the bid ceiling, sold comps feed and asking comps are separate (C-04, C-10, B-08), profit per hour, merchandising (`merchandising.py`), flip lane, owned-asset five-path card.
- Spine: items, requests, approval gates with PIN, ledger/outcomes, receipts with provenance, research ledger, R14 owner channel.
- UI: glanceable Today and Approve / Hold / Pass already pushed by lane 06 (F-38, receipt 2026-10-09).

## 3. Gaps against the directive (INFER unless marked)
| # | Directive point | Gap |
|---|---|---|
| G1 | 2, 3 Arkansas auctions within about 100 miles of Conway | No Arkansas auction-house source or geo filter (distance helper exists in lane 02 `campaigns.py`). Need a source inventory and read-only adapters with robots/terms review (ADR-0202 tiering). |
| G2 | 3 lots, current bid, bid count, closing time, premium, tax, pickup, rules, source and freshness | `buyer_premium_pct`, `bid_count`, `ends_at` partly exist; `sales_tax`, pickup requirements, auction rules text and per-field freshness do not (UNK how much the Item schema allows without a frozen-contract change: additive fields only). |
| G3 | 5, 6 all-in cost, time to cash, capital turnover, 24-48 h flag | Profit and profit per hour exist; time-to-cash, capital turnover and a "slow inventory" flag are not first-class outputs (INFER from engine inputs). Sales tax and pickup/transport are only partly modelled. |
| G4 | 4 completed sales vs asking | Separated already (C-04 vs C-10); needs to be shown on the card and required for YES (check). |
| G5 | 7 watchlists, price and closing alerts, approved bid ceilings | No watchlist store or alert job. Bid ceiling exists only as the engine's walk-away price. No auto-bid and none should exist yet. |
| G6 | 8 resale workflow: intake, photos, listing prep, demand, sale status, realized profit | Owned-asset intake and listing prep (merchandising) and outcome ledger exist; buyer-demand tracking and an end-to-end inventory page are missing. |
| G7 | 9 governance | In place; keep. Automated bidding stays disabled until integration, authorization, rules and receipts are verified. |

## 4. Smallest safe pivot (no deletions, no contract changes)
1. **Park the labor lane in the backlog**: C-31 is PARKED (not deleted); no new service-lead tasks; existing service code stays and its tests stay in the gate. The service lane is not shown on the Today cards (lane 06 already ranks by evidence; F-38 follow-up: filter OPPORTUNITIES to asset deals).
2. **Re-aim discovery**: B-20 (lane 02) Arkansas auction source inventory and read-only adapters within about 100 miles of Conway, statewide only for exceptional margin; record source, fetch time and freshness per field. Fixtures first; live fetch needs the existing B-12 owner step.
3. **Re-aim economics**: C-32 (lane 03) auction cost model: buyer premium, sales tax, pickup/transport, time to cash, capital turnover, 24-48 h flag and slow-inventory flag, asking vs completed separation enforced for YES. Additive config only; no engine contract break (engine version bump with goldens regenerated by the lane).
4. **Then** D-33 (lane 04) watchlist and alert store plus bid ceilings as owner-approved numbers (dry-run, no bid submission), and F-39 (lane 06) resale workflow page. E-lane keeps the rule that bidding is a protected action needing a gate and PIN.
5. P1 repairs keep their order: A-49, then D-32 / F-37 (C-31 parked).

## 5. Tests for acceptance
- Discovery: fixture auctions around Conway produce normalized lots with bid, bid count, closes_at, premium, source and freshness; outside-radius lots are filtered unless the margin test passes; offline guarantee test stays green.
- Economics: golden cases with premium, tax and pickup give the expected all-in cost, net, time to cash and capital turnover; a slow-inventory item is flagged; asking-only comps cannot yield YES.
- State and UI: watchlist alert fires once per event; bid ceiling is stored and shown but no bid path exists (negative test); resale page moves an item from intake to sold and records realized profit with a receipt; Today never labels simulated figures as earnings.
- Gate stays green (500 tests); the frozen-schema hash check stays green.

Status: AUDIT DONE (proposal). Implementation not started; nothing claimed complete. Owner approval is needed only for: live fetches of new sources (terms review), any bid integration, and any spend.
