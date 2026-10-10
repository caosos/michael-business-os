# F-51 / F-52 acceptance matrix

Prepared 2026-10-10 at 04:48 UTC for the existing MBOS coordinator and lane 06. This is an independent review checklist, not another task queue or product specification. **All acceptance cases are NOT RUN.** No browser, application test, external action, repository write, restart, or live reload was performed for this deliverable.

## Source and precedence

- Repository: `caosos/michael-business-os`; branch: `research/agent-01-coordinator`.
- [Authoritative F-51 and F-52 queue rows](https://github.com/caosos/michael-business-os/blob/research/agent-01-coordinator/docs/status/READY_QUEUE.md), fetched 2026-10-10 04:47 UTC; file blob SHA `1a0de603084f219ac987ede79fbab74e5c10217e`.
- [F-51 amendment/handoff](https://github.com/caosos/michael-business-os/blob/research/agent-01-coordinator/docs/handoff/F-51-amendment.md), fetched at the same observation; file blob SHA `ce21cb94d7319114561a8785d9c74852df9fe26d`.
- [Existing amendment evidence](https://github.com/caosos/michael-business-os/blob/research/agent-01-coordinator/docs/receipts/pickup/ARYA-20261010-0433-f51-scope-handoff.md).
- Delivery order: **A strict filters and validation → B browse gallery/category rows → C preference learning**. C must never delay A/B. F-52 begins only after F-51 closes and covers only omissions established by F-51's receipt.
- Parent-provided visual-reference description: Craigslist-like five-across desktop photo-card gallery, narrow sidebar, and configurable three-to-four category rows. No screenshot file was provided or inspected for this review. Treat the five-across target as a supplied visual-reference detail, not an independently verified screenshot finding. The canonical queue itself requires a dense responsive gallery, without a fixed desktop column count. Preserve this provenance when reviewing.
- The amendment text contains a claimed write time of approximately 05:10Z, later than this review's 04:47Z observation. Do not use that text as a verified event timestamp. File contents and blob hashes above are the evidence actually observed.

## Execution boundary and evidence rules

- Existing `/market` application only. Staging acceptance; no new dashboard, parallel datastore, copied marketplace inventory, scraping, credentials, external contact, bid or spend.
- Do not alter the running F-51 worker, its worktree, or its execution process. Coordinator owns delivery/queue reconciliation.
- Live reload remains a separate owner-gated action. This checklist authorizes none. Keep code-complete, tested, staging-accepted and live-accepted separate.
- Use **NOT RUN**, **PASS**, **FAIL**, **BLOCKED**, or **NOT APPLICABLE—with reason** per case. Never infer PASS from a screenshot of another artifact, a task ACK, test totals, or a healthy service.
- Test data below is a deterministic isolated test design, **not real listings or accepted results**. Do not inject it into ordinary staging/live owner inventory. A separate browser pass uses real cached GSA inventory with original IDs and cache timestamps.
- Capture exact code/artifact SHA, staged build identity, test command and exit/result counts, UTC observation time, cache source/hash/as-of, viewport, expected and actual IDs/counts, screenshot path, and failure detail. Redact secrets; do not include resident or unrelated personal data.
- On the same final artifact, rerun affected cases after fixes. A focused pass does not imply the entire matrix passed.

## Controlled fixture design for strict filtering

Use the existing isolated test harness and supported data shape. Suggested abstract records:

| ID | Category | Known price | Known distance from test origin | Purpose |
|---|---|---:|---:|---|
| T1 | trailer | 100 | 10 | exact minimum |
| T2 | trailer | 200 | 50 | exact maximum and radius |
| T3 | equipment | 99 | 10 | below minimum |
| T4 | electronics | 201 | 10 | above maximum |
| T5 | trailer | 150 | 50.01 | just outside radius |
| T6 | equipment | UNKNOWN | 10 | unknown price |
| T7 | electronics | 150 | UNKNOWN | unknown distance |
| T8 | trailer | UNKNOWN | UNKNOWN | both unknown |
| T9 | equipment | 150 | 20 | ordinary included item |
| T10 | electronics | 150 | 30 | ordinary included item in third row |

With minimum 100, maximum 200, radius 50, and all three categories enabled, the normal known-result set is **T1, T2, T9, T10**; T6–T8 are absent unless the separately labelled unknown section is explicitly enabled. T5 must not slip through because a displayed rounded distance looks like 50.0. Distances should come from controlled existing resolver fixtures, not fabricated real-world coordinates.

## A. Strict filters and validation — first acceptance gate

| ID | Case / data | Expected behavior | Required evidence | Status |
|---|---|---|---|---|
| A01 | Fixture baseline: min 100, max 200, radius 50 | Exact known set T1/T2/T9/T10; counts match across all rows | Automated assertion of IDs and counts | NOT RUN |
| A02 | Price = minimum and maximum | T1 and T2 included; inclusive bounds | Boundary unit/integration test | NOT RUN |
| A03 | Price immediately below/above limits | T3 and T4 excluded from every row | Per-row and aggregate assertions | NOT RUN |
| A04 | Distance exactly radius versus 50.01 | T2 included; T5 excluded based on actual computed distance, not rounded label | Resolver/search boundary test | NOT RUN |
| A05 | Unknown price with strict price bound | T6/T8 do not pass normal results | Automated test, normal-section IDs | NOT RUN |
| A06 | Unknown distance with strict radius | T7/T8 do not pass normal results or count as local | Automated test and label assertions | NOT RUN |
| A07 | Explicit unknown-results opt-in on/off | Unknowns appear only in a separately labelled section when enabled; normal/local count remains truthful; toggling off removes them | Browser states and tests | NOT RUN |
| A08 | Global filters with three-to-four category rows | No category bypasses min/max/radius; empty rows do not borrow nonmatching inventory | Per-row ID assertions and screenshot | NOT RUN |
| A09 | Blank optional numeric controls | Blank has a clear documented no-limit/default interpretation; no hidden stale bound or NaN behavior; applied chips match actual query | Test of parser/query + browser labels | NOT RUN |
| A10 | Negative min/max/radius; nonnumeric input | Visible validation; invalid values are not silently ignored or treated as a successful unfiltered search | Direct-query and form tests; screenshot | NOT RUN |
| A11 | Minimum exceeds maximum | Clear validation rather than silently swapped/ignored values or misleading matches | Automated test + browser | NOT RUN |
| A12 | Zero and decimal values | Explicit consistent policy in form and backend; no accidental falsy-value bypass; any rejected value has visible validation | Boundary tests with documented policy | NOT RUN |
| A13 | Valid Conway AR and ZIP 72032 origins | Supported resolution and correct source-grounded distances; approximate-centroid/limited-coverage caveat visible | Existing resolver tests + actual cache/browser evidence | NOT RUN |
| A14 | Unlocated origin | Clear cannot-locate notice; strict radius is not silently disabled and results are not called local | Test + browser screenshot | NOT RUN |
| A15 | Different valid origin/radius | Result set changes correctly using known coordinates; no invented location for unsupported town | Expected IDs/distance oracle and test | NOT RUN |
| A16 | Entered min/max, slider and applied chips | Numeric inputs and accessible range slider agree; keyboard operation works; chips reflect actual applied constraints | Keyboard browser pass + automated state test | NOT RUN |
| A17 | Navigation, saved search and reload | Entered constraints persist as specified; saved search reproduces same query without relaxing strict limits | Save/nav/reload browser steps + persistence test | NOT RUN |
| A18 | Query yields zero records | Honest zero/no matching known inventory; no demo/filler/recommended-outside-limits substitute | Automated empty-state assertion + screenshot | NOT RUN |
| A19 | Regression against former unknown-allowed tests | Tests previously encoding unknown pass-through are corrected; failure injection/old behavior fails new cases | Old behavior versus fixed test results, exact SHA | NOT RUN |

Unknown opt-in must not conceal the reason an item fails. If the implementation's handling of unknown values plus a separate known-value violation is ambiguous, record it as an explicit gap for coordinator resolution rather than claiming acceptance.

## B. Browse gallery and product truth — second acceptance gate

| ID | Case / data | Expected behavior | Required evidence | Status |
|---|---|---|---|---|
| B01 | Desktop first view at 1648×1000 CSS pixels | Browse-first dense photo gallery, narrow left sidebar, search/sort/view above results; supplied five-across reference assessed without unreadable cards | Full viewport screenshot; column count and usability notes | NOT RUN |
| B02 | Desktop at 1280×800 | Responsive density and readable cards; no clipped filters or forced five-column crowding | Screenshot and overflow check | NOT RUN |
| B03 | Mobile 390×844 | Search, filters, category rows and cards usable without horizontal page overflow; accessible controls and disclosure | Full-page and first-viewport screenshots + keyboard/touch checks | NOT RUN |
| B04 | Sidebar and top controls | Category checkboxes, ZIP/origin/radius, min/max price; top search/sort/view; advanced filters behind disclosure | Screenshots + interaction evidence | NOT RUN |
| B05 | Three-to-four configurable category rows | Trailers first by default; owner can choose categories and reorder; reload preserves selection/order; all rows obey A | Automated persistence test + before/after/reload screenshots | NOT RUN |
| B06 | Default versus broad inventory mode | Repairable trailers/equipment near Conway by default; editable category/keywords; broad mode explicit and off by default; unknown condition not fabricated | Fresh-state test and browser screenshots | NOT RUN |
| B07 | Card with complete source data | Photo, price attached, short title, town, posted age when known, source/freshness, favorite/hide controls; source values preserved | Record-to-card comparison and screenshot | NOT RUN |
| B08 | Missing photo / inaccessible GSA image | Honest placeholder and original-listing route; no fabricated image, broken-image presentation or token/login bypass | Failure-path test + actual affected GSA card | NOT RUN |
| B09 | Missing posted date / town / condition | UNKNOWN or honest omission, never invented posted age, location or condition | Fixture test + screenshot | NOT RUN |
| B10 | GSA auction card | Plain-language government surplus auctions label; current bid distinguished from asking/final cost; all-in cost unknown where unsupported | Card assertion + browser | NOT RUN |
| B11 | Cache/source freshness | Real source/as-of visible; cached search never described as fresh network fetch; GSA-only coverage clear; stale cache truth retained | Cache metadata + screenshot + no-fetch assertion where applicable | NOT RUN |
| B12 | Original listing link | Link belongs to displayed real source record; no example.invalid, fabricated listing URL or substituted inventory | Source-to-link assertion and safe read-only link check | NOT RUN |
| B13 | Normal navigation/routes | No training/demo navigation or fictional records in normal owner workflow; demo only explicit separate route; history preserved | Route walk with path list and zero-hit checks | NOT RUN |
| B14 | Capital presentation | Working-capital setting separate from verified cash; example slider range is not a budget, spend approval or profit claim | Copy assertions + screenshot | NOT RUN |
| B15 | Search and Save appearance | Controls visibly operable; prior faded state diagnosed as CSS/disabled/focus rather than guessed; validation/loading states truthful | Real-browser computed-state findings, before/after screenshot | NOT RUN |
| B16 | Repeated search / category changes / back navigation | Latest form/query/results consistent; no stale previous-result count or phantom applied filter | Repeated-flow browser record | NOT RUN |
| B17 | Empty category amid populated categories | Exact honest empty-category message; no demo/filler/cross-category content inserted | Screenshot and row-level assertions | NOT RUN |
| B18 | Source strings with HTML/special characters | Text escaped; no executable markup; original wording not misleadingly rewritten | Injection fixture test | NOT RUN |
| B19 | Real cached Conway staging scenario | Record actual origin, keyword/category, bounds, source lot IDs/counts, cache as-of; changing min/max/radius changes correct known set; zero legitimate when appropriate | Staging screenshots at desktop/390px, raw source comparison, SHA | NOT RUN |

Desktop five-across is a reference target at adequate width, not permission to sacrifice legibility or responsive behavior. No Craigslist/Facebook branding, copyrighted screenshot copying, or third-party inventory import is required or authorized.

## C. Preference learning — only after A and B

| ID | Case / data | Expected behavior | Required evidence | Status |
|---|---|---|---|---|
| C01 | Explicit save/dismiss and more/less-like-this | Feedback recorded in existing in-app persistence with truthful UI; survives reload | State/persistence test + browser | NOT RUN |
| C02 | Category order plus explicit feedback | Explainable ranking changes; visible why-suggested tied to actual input, not invented preferences | Deterministic ranking assertion + explanation screenshot | NOT RUN |
| C03 | Favorite high-price/out-of-radius/excluded record | Learning cannot override hard min/max/radius/category exclusions; no resurrected hard-filtered item | Adversarial ranking/filter test | NOT RUN |
| C04 | Unknown price/distance favored by feedback | Unknowns remain subject to separate opt-in and are not presented as local/qualified | Test of combined ranking and strict-filter path | NOT RUN |
| C05 | Disable learning | Documented neutral ordering returns; saved data treatment clearly described; no hidden personalization continues | Before/after/reload test | NOT RUN |
| C06 | Reset preferences | Existing supported reset clears learned influence as described, with deterministic verification | Persistence and ranking test | NOT RUN |
| C07 | Explanation/economic claims | No invented profitability, resale estimate, sold comp or authority to purchase; evidence-backed facts only | Copy/source assertions + browser | NOT RUN |
| C08 | Scope and sequencing | No outside personal data, new credentials or paid service; C did not block delivery/acceptance of A/B | Diff/dependency review and task receipts | NOT RUN |

## Coordinator closeout mapping

For each A/B/C case, append to the existing F-51 receipt: case ID → covered/omitted → code SHA → test evidence → staging evidence → limitation. A case without evidence remains NOT RUN or BLOCKED. Map any already-existing behavior to evidence rather than reimplementing it.

Before F-52 starts, read F-51's final receipt and current amendment. F-52 covers only omissions, in A/B/C order, on the existing lane. A pushed amendment or ACK does not establish that the running worker read it; require its receipt/status citation of the amendment and queue version.

Record separate stages:

1. **Code/test evidence:** exact lane head and verified commands, including failing or skipped checks.
2. **Staging acceptance:** same artifact, real-browser screenshots and source/cache evidence.
3. **Live acceptance:** NOT RUN unless separately authorized and actually verified. Preserve owner reload gate and existing rollback method; never infer it from staging.

Stop this independent review once the evidence mapping is delivered to the existing coordinator. No implementation, live monitoring, repeated restart, or new worker is part of this matrix-preparation task.
