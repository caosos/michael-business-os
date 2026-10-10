# DEAL SNIFFER START HERE — product direction, owner intent, and operating model

Status: OWNER DIRECTION / onboarding package for new Michael Business OS agents
Source: Michael's live design conversation with Aria, 2026-10-07
Authority: product/design direction only. No live spend, contact, bid, payment, publishing, deployment, or external commitment is authorized by this document.

## 1. What Deal Sniffer actually is

Deal Sniffer is not merely a flip finder.

The broader mission is:

> Given Michael's skills, time, location, available capital, and weekly income target, continuously find the best legal path to close the income gap.

A useful weekly mission may combine:
- service work
- smart-home work
- repair/diagnostic jobs
- micro-flips
- standard flips
- larger/capital-intensive flips
- wanted-item opportunities
- auctions
- other legal opportunities that match Michael's skills and constraints

The system should optimize for real cash generation, not for keeping capital deployed.

A valid recommendation may be: **do not spend the bankroll** if low-cash service work offers a better path to the weekly target.

### Current owner capital model

Michael set an initial project bankroll of **$500 total protected principal**.

When a flip closes:
1. acquisition + repair/material principal returns to protected bankroll;
2. realized profit becomes earned working capital;
3. the system should increasingly operate from earned profits while preserving original principal.

Track at minimum:
- protected_principal
- earned_working_capital
- capital_deployed
- realized_profit
- available_to_deploy

There is no universal "$300 profit minimum." Small, fast, low-risk flips may outrank larger slow deals.

## 2. Weekly Money Mission

Deal Sniffer should support an owner mission such as:

- available capital: $500
- weekly target: e.g. $1,500
- available time: Michael's actual hours
- skill/physical constraints: known operator profile

The system should:
1. continuously discover opportunities;
2. estimate profit, risk, probability, time-to-cash and operator time;
3. construct combinations of opportunities that can plausibly close the weekly gap;
4. protect capital and avoid unnecessary lockup;
5. replace failed/stale opportunities automatically;
6. show Michael the smallest number of high-value decisions needed.

The operator UI should eventually be able to show:
- weekly target
- cash already realized
- expected cash from active work
- remaining gap
- best next opportunities
- projected week if current plan succeeds
- risk/confidence around that projection

## 3. Core economic logic

Do not collapse economics into one unexplained score.

Explicitly represent:
- cash_at_risk
- expected_days_to_cash / range
- capital_velocity
- gross_profit_range
- expected net profit
- profit_per_hour
- cash_multiple / ROI
- seasonality
- liquidity
- repair uncertainty
- catastrophic downside probability
- parts-out / liquidation floor
- transport and handling burden
- skill fit
- personal-use value when relevant
- current cash context / capital-lockup sensitivity

Useful opportunity classes include:
- MICRO_FLIP / QUICK_TURN
- STANDARD_FLIP
- CAPITAL_INTENSIVE_FLIP
- SERVICE_JOB
- OTHER_OPPORTUNITY

A $30 item that can become $75-$100 in an hour may be a better current opportunity than a $250 item that becomes $600 in four months.

The system must distinguish:
- good asset
from
- good buy for Michael right now.

## 4. Opportunity card philosophy

The machine may use a score internally. Michael needs an explanation.

Every strong Deal Sniffer card should show, when evidence exists:
- current listing photos
- item / make / model / category
- ask / budget / location / distance / source
- original post date
- latest edit/update date
- listing age
- suspected relist
- stale risk
- seller/account intelligence where the source exposes it
- confidence and UNKNOWN fields rather than fabricated values
- plain-English "why Deal Sniffer likes it"
- recommended opening offer
- maximum acquisition
- repair/material estimate
- transport estimate
- all-in cash at risk
- conservative / likely / optimistic resale
- expected gross/net profit
- profit/hour
- expected days-to-cash
- value-add plan
- model-specific failure modes and expensive parts
- parts availability
- seasonality
- logistics / truck vs trailer
- recommendation: CONTACT / OFFER / BUY / COUNTER / HOLD / PASS
- status timeline
- complete activity trail with receipts and provenance

Do not fill cards with elementary mechanic advice unless it is model-specific and materially relevant.

Future visual feature:
- clearly label current listing imagery separately from an AI-generated "possible finished look."

## 5. Conversational intake is the product interface

Users should interact with the platform the way Michael interacts with Aria.

They should not need to understand a giant form.

Example:

> "I need somebody to replace this rotten section of floor. Here are pictures. I want it done next week."

The system asks only the missing questions needed to create a valid transaction/job object.

Same for selling:

> "I want to sell this mower. It runs but smokes. I want at least $400."

The system should:
- inspect supplied photos;
- identify category/model where reasonably possible;
- ask for serial/model/title/ownership evidence when relevant;
- request missing photo angles/evidence;
- ask known-defect questions;
- estimate a price range when evidence supports it;
- refuse to mark unsupported claims as verified;
- transform natural conversation into structured data behind the scenes.

Product principle:

> **Talk naturally. The system does the paperwork.**

Related principle:

> **Users provide intent and evidence. The system turns it into a valid transaction object.**

## 6. Evidence-rich listings

The more useful information a seller supplies, the better the listing can be classified and marketed.

A seller should be prompted for category-specific evidence:
- required photo angles
- model/serial/VIN where appropriate
- ownership/title status where relevant
- condition questions
- known defects
- operating status
- repair history
- included accessories/parts
- pickup/delivery terms

The system should distinguish:
- seller-stated
- system-inferred
- independently verified
- UNKNOWN

A buyer may place:
- unconditional bid based on disclosed evidence
or
- conditional bid with explicit contingencies.

Example:
- "I bid $850 contingent on cold start, title matching VIN, and no undisclosed frame damage."

If the condition basis is met, the buyer is committed under the platform's rules.
If material seller misrepresentation is proven, that should affect dispute handling and reputation.

## 7. Category-aware marketing of the same inventory

The same underlying item should be presentable differently to different audiences without changing the truth.

Example:
a non-running vehicle or mower may appear as:
- ordinary local classified listing
- "mechanic special"
- flipper opportunity
- parts/donor opportunity
- project vehicle/equipment
- auction candidate
- quick-turn candidate

This is not duplicate data. It is **one canonical inventory object with multiple truthful merchandising views**.

The system should classify inventory based on evidence and seller answers, then market it to the audiences most likely to care.

Examples of audience segments:
- mechanics
- flippers
- DIY/project buyers
- collectors
- homeowners
- contractors
- parts buyers
- bargain hunters
- commercial buyers

The system may rewrite presentation, headline, ordering of facts, and highlighted economics for an audience, but it must never invent or hide material facts.

## 8. Marketplace direction

Long-term, Deal Sniffer can grow into a local opportunity marketplace rather than only a private operator tool.

Core transaction directions:

### Seller posts item
Buyers:
- buy now
- make offer
- bid in auction

### Buyer posts wanted item
Sellers:
- respond with matching inventory
- compete for the buyer's demand

### Customer posts job
Providers:
- bid / quote / respond

### Provider posts service
Customers:
- request / book / negotiate

One account may act as buyer, seller, customer, or provider at different times.

The marketplace should retain a simple Craigslist/PennySaver-like surface while hiding sophisticated transaction infrastructure underneath.

## 9. Wanted campaigns / persistent demand

A user should be able to launch a campaign such as:

> "Find me a 5x8 utility trailer within 40 miles, max $600, title preferred, cosmetics don't matter."

Campaign autonomy levels can include:
- WATCH ONLY — notify on matches
- RECOMMEND — suggest what to offer
- ASSISTED DEAL — draft offer/counter, wait for approval
- BOUNDED AUTOPILOT — act only within explicit user-defined limits, when governance eventually allows it

Campaign engine may:
- watch new listings
- watch auctions
- compare against user criteria
- rank matches
- notify
- draft offers
- negotiate within bounded authority later
- stop when fulfilled
- record every action/decision

Visible demand is valuable data. The system can eventually see that many buyers want a category before a flipper buys inventory.

That can transform flipping from:
- buy → fix → hope
into:
- see demand → source → add value → sell into known demand.

## 10. Auctions, offers, and commitment

A platform bid should mean more than a Marketplace message.

Long-term model:
- verified user/account
- valid payment method
- bid / offer / quote
- category-appropriate deposit or authorization
- acceptance / auction close
- transaction lock
- pickup / service / delivery
- completion
- payment release
- receipt
- reputation update

Do not make Deal Sniffer itself the bank. Use a marketplace payment provider for payment authorization, payouts, refunds, KYC/identity obligations where applicable, and related compliance.

Different categories may use different commitment structures:
- low-value goods: full authorization or small deposit
- vehicles/high-value goods: winning deposit + balance at pickup
- service work: booking deposit / milestones / final payment

Once both sides commit, the item/job should leave the open market under clearly defined terms.

## 11. Reputation must be behavior-based

Do not reduce trust to arbitrary stars.

Useful measurable history may include:
- verified identity
- verified payment
- completed purchases/sales/jobs
- completion rate
- no-show rate
- unpaid winning bids
- cancellation rate
- response time
- on-time completion
- verified disputes and outcomes
- seller misrepresentation findings
- contractor/provider credentials where applicable

Credential status must be specific, e.g.:
- identity verified
- payment verified
- insurance verified
- residential license verified/not provided
- electrical license verified/not provided

"Verified" must never ambiguously imply every possible license or credential.

Reputation penalties must be evidence-based, graduated, and appealable rather than arbitrary "docking."

## 12. Service work and local rules

The platform is not "licensed contractors only."

Ordinary lawful work can be bid by ordinary verified providers when the applicable jurisdiction does not require a specific credential.

The system should determine eligibility from:
- work location
- city/county/state jurisdiction
- type/scope of work
- applicable thresholds
- credential requirements
- permit considerations

Do not hard-code broad assumptions such as "outside city limits means no license required."

Instead use jurisdiction packs, starting locally and expanding.

Possible pilot structure:
- supported city
- surrounding county
- unincorporated area
- supported job classes
- rule source
- last verified date
- credential requirement
- permit notes
- confidence / unresolved questions

The system should state:
- what rule it found
- source
- date verified
- confidence
rather than inventing certainty.

## 13. Valuator

The platform should have a valuation engine.

For homes, a user may provide:
- address/property record
- photos
- improvements
- defects
- condition answers

The result should be a range and strategy, not a fake precise number:
- suggested list range
- likely sale range
- fast-sale range
- as-is estimate
- after-repair estimate where evidence supports it
- confidence
- reasons/comps/evidence

Do not represent an automated estimate as a licensed appraisal.

The same general engine can extend to:
- cars
- trailers
- mowers
- equipment
- furniture
- collectibles
- service jobs

Long-term marketplace transaction data becomes valuable valuation evidence:
ask → offers → accepted price → actually paid → completed.

### 13a. Trailer visual-inspection buying guideline (owner-required; ARYA-20261010-1812)

Michael explicitly required this as canonical decision guidance: the system must have eyes on what a trailer actually looks like before recommending it. This is a **guideline**, not a claim that an automated visual-inspection feature exists.

Rules:
- Open and visually inspect the actual listing photographs before recommending a trailer or selecting like-for-like comparables. Dimensions and sale price alone are insufficient.
- Separate **visible facts**, **seller claims** and **unknowns**. A light-duty/heavy-duty characterization from photographs is provisional.
- Verify capacity from manufacturer documentation and the VIN/certification label (GVWR/GAWR). Never infer safe capacity from wheel size, apparent construction or dimensions.
- Compare construction, verified capacity, condition, gate/ramp, paperwork and all-in cost. A generic 5x8 listing is not automatically comparable.
- Insufficient photos or capacity evidence means the verdict is **needs photographs/inspection**; do not label it a good buy.
- Light-duty trailers are **not categorically excluded** (ARYA-20261010-1819). They may be appropriate when condition, verified capacity, total cost and supported repair/resale margin fit the intended use. The rule is to visually inspect and compare like-for-like, not to require heavy-duty construction. No private purchase ceilings, budgets or resale estimates belong in this document.

Minimum photo evidence: front, rear and both sides; underside rails and crossmembers; full tongue and its connections; axle, springs and hubs; both sides of the deck; tire date and load markings; VIN/capacity label; gate/ramp, coupler, chains and lights.

Reviewed public example: HiBid item 323080435 sold for $575. Photos show a mesh deck, low rails, small wheels, a central tongue and rust/discoloration. Likely light-duty is provisional; capacity and hidden frame condition remain unknown. The sold price is a valid historical sale datapoint, not a recommendation or like-for-like valuation.

### 13b. Component and exit-path assessment guideline (owner core objective; ARYA-20261010-1911)

Michael described this as Deal Sniffer's absolute objective: "I want to look at these things and piece them out." The assessment must reflect his practical mechanical and welding capability; a nonrunning asset is not automatically worthless or unsuitable. This is a **guideline**, not a claim that automated component assessment exists.

Exit paths (mutually exclusive per asset): (1) sell whole as-is; (2) repair and resell; (3) part out; (4) repurpose or convert. State which path fits the available evidence and why. Never add the whole asset's sale value to the sale values of its own components.

Rules:
- Itemize recoverable components (engine, trailer, controls, other usable parts). For each, separate **visible condition**, **seller claims**, **tested facts** and **unknowns**. Inspect the actual listing photos and obtain missing evidence; never infer serviceability or capacity.
- Use relevant sold comparables per exit path and per component. Keep asking prices apart from realized sales; adjust for condition, compatibility and realistic demand. Unsupported estimates are labelled **unknown** or **provisional**.
- A nonrunning whole asset may be attractive if supported component recovery justifies total cost and effort. Do not reject it solely because it does not run.
- Cost the full path: needed parts, work, fuel, fees, paperwork/title, disposal, storage and time to sell. Model realistic liquidation, unsold components and residual disposal, not prompt sale at best asking price.
- Distinguish work Michael can do himself (mechanical, welding) from work needing outside help, time/opportunity cost, and actual cash outlay. Do not price all labor or transport as hired, and do not assume tools, transport capacity or unlimited time.
- Repurposing needs a supported feasibility assessment. Example: a boat-trailer frame is not automatically suitable as a car trailer. Verify frame, axle, brakes, load distribution, manufacturer GVWR/GAWR and applicable engineering/safety requirements. Unknown capacity stays unknown; skill does not replace structural or capacity evidence.
- No private prices, budgets, purchase ceilings or personal financial examples belong in this document.

#### 13b-1. Heavy scrap / component recovery feasibility gate (owner decision rule; ARYA-20261010-2113)

Owner rule: a bid cannot be made when the cost of moving a very heavy machine is unknown. A heavy asset valued on scrap or component recovery gets **no bid recommendation** until one of these is satisfied:
- **(a)** a yard is verified to accept the actual material/item, with supported **net** pickup-offer evidence; or
- **(b)** realistic transport, loading/unloading and any needed cutting/disassembly costs are established.

Evidence required before any bid ceiling is derived:
- Actual weight and dimensions; loading equipment/capability and site access; pickup deadline and removal obligations; title/paperwork; all applicable fees. Seller loading help or yard pickup is **not** assumed.
- Gross scrap value is kept separate from **net realized proceeds** after pickup/transport/cutting/fees/disposal. Whole-asset scrap and component values are alternatives (see exit paths above); never add them together.
- If any material transport/removal cost is unknown, output **BLOCKED: missing evidence** and list the exact missing items. Do not substitute an invented profit figure.
- "Why didn't the seller scrap it?" is a due-diligence question, not evidence of a bad deal, guaranteed profit or hidden defect. Hypotheses stay labelled as hypotheses until verified.

This is a documented guideline only; no automated implementation exists. No yard contact, bids or purchases are authorised by it.


## 14. Inventory merchandising

The system should actively make inventory interesting and engaging.

For the same canonical listing, it can generate truthful audience-specific presentations such as:
- "Mechanic Special"
- "Project / Fix & Flip"
- "Ready to Work"
- "Parts / Donor"
- "Quick Turn"
- "Auction"
- "Wanted Match"
- "Contractor Opportunity"

Presentation may change:
- headline
- image ordering
- which facts are emphasized
- economic framing
- audience language
- call-to-action

But must preserve:
- condition truth
- known defects
- evidence basis
- price/bid terms
- provenance

Marketing should improve discovery without becoming deception.

## 15. Why the marketplace matters

The central problem being addressed is not merely discovery.

Existing local marketplaces often have weak commitment:
- many messages, few real buyers
- no-shows
- seller sells while buyer is traveling
- weak condition evidence
- poor transaction history
- little meaningful paper trail

Deal Sniffer's long-term differentiation is:

> **simple local marketplace on the surface; verified commitment, evidence, intelligent matching, and receipts underneath.**

AI is the intelligence layer.
The transaction structure is the trust layer.

## 16. Product growth path

Do not try to build Craigslist + eBay + Thumbtack + Zillow + escrow simultaneously.

### Level 1 — Make Michael money
- private Deal Sniffer
- real opportunity discovery
- service + flip ranking
- weekly money mission
- operator UI
- real outcomes
- learn from results

### Level 2 — Transaction engine
- structured offers
- bids
- counters
- contingencies
- acceptance
- reputation
- category-aware transaction rules
- payment-provider integration in a controlled scope

### Level 3 — Public marketplace
- buyers
- sellers
- customers
- providers
- auctions
- wanted campaigns
- valuation
- verified transaction history
- public reputation
- broader jurisdiction packs

## 17. Core product principles

1. **No action without a receipt. No receipt without provenance.**
2. **Talk naturally. The system does the paperwork.**
3. **Users provide intent and evidence. The system turns it into a valid transaction object.**
4. **A machine score is for ranking; the explanation is for the human.**
5. **Do not fabricate missing data. UNKNOWN is valid.**
6. **Do not use a universal absolute-profit floor.**
7. **Optimize for current owner goals, capital velocity, time-to-cash, risk and fit.**
8. **One canonical item/job can have multiple truthful audience-specific presentations.**
9. **A bid should mean something.**
10. **Reputation should come from documented behavior, not only stars.**
11. **Use the actual local rule set; do not over-regulate users beyond it.**
12. **Start local, prove the loop, then expand.**
13. **Build the machine for Michael first; then turn the machine into the market.**

## 18. Immediate implementation implication

This document is product direction, not authorization to derail the MVP.

Agent 01 should:
1. reconcile this document with current contracts, scoring, card schema, operator UI, queue and ADRs;
2. separate immediate MVP needs from future marketplace architecture;
3. create bounded tasks for missing current-scope capabilities such as:
   - weekly money mission / portfolio-of-opportunities planning
   - category-aware merchandising fields/views
   - canonical inventory with audience-specific presentation
   - richer opportunity classification
   - campaign/wanted-object model seams where useful without overbuilding
4. keep live external actions DRY-RUN unless separately authorized;
5. prevent future architectural decisions from unnecessarily blocking marketplace expansion.

## 19. Onboarding requirement

Any new Business OS / Deal Sniffer agent should read this document after START_HERE.md and before proposing product behavior that touches:
- scoring
- discovery
- opportunity ranking
- cards/UI
- inventory/listings
- campaigns
- offers/bids
- services/jobs
- marketplace architecture
- valuation
- payments
- reputation
- legal/jurisdiction handling
- marketing/merchandising

If this document conflicts with a later explicit Michael decision or accepted ADR, the later explicit decision wins and this document should be amended with provenance.

## Current /market status pointer (ARYA-0447; 2026-10-10)
Strict price/distance filtering and the gallery are in flight as **F-51** (amended scope: `docs/handoff/F-51-amendment.md`), with **F-52** as follow-on. Code complete: no. Staging acceptance: no. Live acceptance: no (owner-gated reload). Known defect and history: `docs/operations/AI_PROJECT_OPERATING_BLUEPRINT.md`, "Troubleshooting history".
