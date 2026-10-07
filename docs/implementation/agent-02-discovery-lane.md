# DISCOVER + NORMALIZE lane — wave-one implementation (Agent 02)

**Date:** 2026-10-07 · **Contracts:** frozen v1.0.0 (agent-01-coordinator @ `1269405`, vendored + hash-pinned)
**Package:** `src/mbos_discovery` (Python 3.12, one runtime dependency: `jsonschema`)
Tags: **FACT** (verified by code/tests in this branch), **INFERENCE**, **RECOMMENDATION**, **UNKNOWN**.

## 1. What exists

| Module | Job |
|---|---|
| `adapter.py` | `SourceAdapter` ABC: `fetch(profile) → FetchResult` (never raises) and pure `normalize(payload, fetched_at) → Normalized`. No other public methods — FACT (`test_adapter_interface_has_no_effectors`). |
| `http.py` | `ReadOnlyTransport`: https only; GET only to allow-listed hosts; POST only to allow-listed OAuth token URLs; PUT/DELETE/other refused before the network. |
| `policy.py` | ADR-02-0202 registry: ALLOWED / PENDING_MICHAEL / FORBIDDEN. Unknown sources fail closed. FORBIDDEN cannot be enabled by any flag. |
| `rawstore.py` | Content-addressed, immutable raw retention (`sha256:<hex>`); FS layout `raw/sha256/ab/cd/<hex>`, read-back is hash-verified. |
| `normalize.py` | Ordered keyword classifier (flip + service categories from Item v1), text cleaning, money/timestamp parsing, rings → `geo_tier`, flags, prompt-injection detection. |
| `dedup.py` | `dedup_key` (contract-example format), `content_hash`, cross-source matcher. |
| `store.py` | Staging store: Items, append-only provenance, ledger events with `receipt_intent`s. The only write path in the lane. |
| `pipeline.py` | `run_discovery()`: retain raw → normalize → provenance → contract check → observe. Per-source and per-record failure isolation. |
| `health.py` | Per-source HEALTHY/DEGRADED/FROZEN; block freeze + `freeze_request` for 05's L2 freeze. |
| `adapters/ebay_browse.py` | Flip lane, tier 1, live OAuth path + fixture mode running the same code. |
| `adapters/service_intake.py` | Service lane, tier 1: website-form and referral submissions from a local inbox (read-only). |
| `cli.py` | `mbos-discover run|health|clear-freeze`. |

## 2. Invariants and where they are proven (all FACT — `pytest`, 56 tests green)

| Requirement | Mechanism | Test(s) |
|---|---|---|
| Every Item has `sources[]` | store only creates Items from a sighting; `contract.check_item` | `test_every_item_has_sources_and_raw_ref` |
| Every Item has `raw_ref` (stricter than schema: **every sighting**) | raw bytes stored *before* normalize; missing ref fails `check_item` | same + `test_contract_check_rejects_item_without_raw_ref` |
| Items/Provenance conform to frozen contracts | jsonschema against vendored v1.0.0 for trial + final Item | `test_items_and_provenance_validate_against_frozen_contracts`, `test_vendored_contracts_match_freeze` |
| Normalization deterministic | pure `normalize`; derived ULIDs; injected clock; canonical JSON | `test_normalize_is_pure`, `test_two_independent_runs_are_byte_identical`, `test_item_replays_from_raw_ref` |
| Repeated discovery → no duplicates | `(source, listing_id)` index; unchanged content = SEEN (no new event/provenance) | `test_repeated_discovery_creates_no_duplicates`, `test_same_listing_from_two_queries_is_one_item` |
| Cross-source dedup | category + price ±15% + same place + title similarity ≥ 0.85 → MERGED sighting | `test_cross_source_duplicate_merges_as_sighting`, `test_same_source_lookalikes_are_not_merged` |
| Service dedup | hashed contact + category within 14 days | `test_service_lead_seen_twice_merges_by_contact`, `test_service_dedup_window` |
| Source failures fail safely | fetch never raises out; crash contained; failed source leaves store untouched; bad record quarantined with raw kept | `tests/test_failures.py` (crash, 503, malformed record, malformed file, missing creds, missing inbox) |
| F3 repeated 403/429 → freeze | 2 consecutive blocks (or 1 CAPTCHA) → FROZEN, `freeze_request{level:L2, capability:discovery.source.<s>.read}`, zero further requests until a human clears | `test_repeated_block_freezes_source_and_stops_requests`, `test_captcha_freezes_immediately`, `test_freeze_cleared_only_by_human_then_recovers` |
| F4 do-not-automate never touched | policy check precedes fetch; FORBIDDEN ignores enable flags | `test_forbidden_sources_never_fetched_even_if_enabled` (8 sources), `test_gray_zone_and_unknown_sources_need_explicit_enablement` |
| No side effects | ReadOnlyTransport; intake never moves/deletes files | `test_read_only_transport_refuses_writes` (bid/checkout URLs), `test_fixture_run_makes_only_token_post_and_search_gets`, `test_intake_never_modifies_inbox` |
| Untrusted text | injection patterns → `injection_suspected` + `needs_review`; state stays NORMALIZED | `test_untrusted_text_is_flagged_not_obeyed` |

F2 (dup rate < 2% on a 7-day sample) — **UNKNOWN** until live data runs for a week.

## 3. `raw_ref` retention rule (answers gap request 02-(2))
1. Raw bytes are stored exactly as received per record (API: canonical JSON of the item object; intake: the file bytes, even if unparseable) **before** normalization.
2. Objects are immutable and never deleted by this lane. RECOMMENDATION: retain ≥ 18 months (covers LEARN calibration on sold outcomes); 04 owns lifecycle in the artifact store.
3. `sources[i].raw_ref` + `provenance_id` point at the payload that the sighting's **current** data came from. On a source-side change the sighting is re-pointed; earlier payloads stay reachable via `Item.provenance_ids → inputs_used[].hash`.
4. Replay: `adapter.normalize(json.loads(raw.get(raw_ref)), provenance.fetched_at) == Item.normalized` for the primary sighting (tested).

## 4. Field mapping raw → Item v1

**eBay Browse `itemSummary` → Item** (flip)

| Item | eBay field |
|---|---|
| `sources[].source_listing_id` / `url` | `itemId` / `itemWebUrl` |
| `opportunity_kind` | `AUCTION` ∈ `buyingOptions` → `auction_lot`, else `buy_item` |
| `normalized.price` | auction with bids → `currentBidPrice` (`auction_current`); auction no bids → `starting_bid`; else `price` (`fixed`; 0 → `free`) |
| `normalized.condition` | `conditionId` <2000 new · 2000–6999 used · ≥7000 parts; fallback `condition` text |
| `normalized.ends_at` / `bid_count` | `itemEndDate` / `bidCount` |
| `normalized.location` | `itemLocation.city/stateOrProvince/postalCode` (eBay masks zip, e.g. `720**`); `geo_tier` from `distanceFromPickupLocation` |
| `normalized.counterparty` | role seller, `contact_method: platform`, `name` = username, `is_dealer` = `sellerAccountType == BUSINESS` |
| `category` / `subcategory` | classifier over title, then title + `categories[].categoryName` / first category name |

**Intake submission → Item** (service): `submission_id` → listing id; `url = intake://<channel>/<id>`; `service_requested` → title + primary classification text; `budget` → `price{customer_budget}` else `quote_requested`; `preferred_contact`/email/phone → `contact_method` only (values stay in raw); `condition: n/a`, `listing_status: open`, `opportunity_kind: service_lead`.

## 5. Hand-offs
- **04 (State):** consume `items.json` / `ItemStore.to_json()` and `events[].receipt_intent` — Receipt v1 minus `receipt_id, seq, prev_hash, row_hash`, with `idempotency_key`, `provenance_ids`, `artifact_hashes=[raw_ref]`. `raw/` is already in artifact-store layout. RECOMMENDATION: 04 replaces `ItemStore` behind the same `observe()` signature with a State-MCP-backed writer.
- **05 (Governance):** `RunReport.freeze_requests[]` → L2 capability freeze. The lane freezes locally regardless.
- **03 (Economics):** Items arrive in `NORMALIZED` with no `economics`. `road_miles_one_way` intentionally **not** set — only `geo_tier` from straight-line/pickup distance (INFERENCE-grade); distance cost is 03's.
- **DBOS (01/A):** `run_discovery` is a single deterministic step given `(jobs, now)`; wrap per source as a DBOS step on a cron.

## 6. Contract gaps found (for Agent 01; not changed here)
1. `sources[].raw_ref` is optional in item.schema.json, but F1 requires it. This lane enforces it; RECOMMENDATION: make it required in v1.1 (the service example lacks it).
2. Receipt `type` has no non-transition item event (merge / source-side update). The lane emits `ITEM_STATE_CHANGED` with equal before/after state and `effect: update`; RECOMMENDATION: add `ITEM_UPDATED` (or `SOURCE_SIGHTING_RECORDED`).
3. No Receipt type for source freezes (`KILL_SWITCH_CHANGED` is the closest); 05 to decide.
4. `normalized.images` requires sha256 refs — image download is deferred (wave two); URLs remain in raw.

## 7. Not done yet (RECOMMENDATION order)
GSA Auctions and Trash Nothing are done (§10). Remaining: IMAP alert ingestor → SAM.gov. Craigslist stays PENDING_MICHAEL. No Facebook / Nextdoor.

## 8. Run it
```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/mbos-discover run --config config/discovery.example.toml --fixtures tests/fixtures   # offline
EBAY_CLIENT_ID=... EBAY_CLIENT_SECRET=... .venv/bin/mbos-discover run --config config/discovery.example.toml  # live
.venv/bin/mbos-discover health
.venv/bin/mbos-discover clear-freeze ebay --by michael
```

## 9. Spine seam — READY_QUEUE B-01 (rulings R5, R8; ROUND_TWO_INTEGRATION §3-B)

`src/mbos_discovery/spine.py` implements Agent 01's `mbos.interfaces` (@ `99e9ec0`) without touching the spine:

| Protocol | Class | Behaviour |
|---|---|---|
| `SourceAdapter` | `SpineSourceAdapter` (one per adapter × profile, named `<source>:<profile_id>`) | policy → freeze check → `fetch` → retain raw → `normalize` (for identity only) → `RawListing`. Sorted by listing id; never raises for a source problem; `version` = adapter version (used by the workflow for provenance) |
| `Normalizer` | `SpineNormalizer` | dispatch on `raw.source` to the adapter's pure `normalize`; emits `NormalizedListing` with blocking `dedup_key` + `content_hash`; `economics=None` (RESEARCH producer is C-01) |
| `Deduper` | `SpineDeduper` | flip: `is_cross_source_duplicate` (same type/category, price ±15 %, same place, title ≥ 0.85); service: same `fp-` blocking key and the existing Item not in a terminal state |
| side channel | `SideChannel` (JSONL) | `skipped`, `source_error`, `freeze_request` (`{level: L2, capability: discovery.source.<s>.read}`), `quarantine` — outside the DBOS-checkpointed listing stream (R5) |

**`raw_ref` (ruling: hash of the stored raw bytes).** JSON payloads are now retained as MBOS-CJSON-1 bytes (ADR-0010
reference, vendored byte-identical and hash-pinned). That is exactly what `mbos.spine.ingest` writes to
`mbos.artifacts`, so both lanes store the same bytes under the same `raw_ref`, with no spine change needed (FACT:
`test_fixtures_through_real_spine_identity_first` compares the bytes in `mbos.artifacts` with ours). Payloads outside
the profile, and unparseable files, are kept as received and quarantined.

**Service blocking key** is now `<category>|lead|fp-<first 16 hex of sha256(contact)>`. The spine's `Deduper`
call carries no contact, so the fingerprint has to travel in the key. It is a pseudonymous hash; raw contact
values stay in the raw artifact only.

**Seam gap (for Agent 01 / ADR-0009):** `Deduper.is_duplicate(existing_item, candidate)` gets no candidate
`source`, so the wave-one rule "never merge two listings from the same source" cannot be enforced on the spine
path. Effect: two identical listings from one seller on one source can become one Item with two sightings.
Nothing is lost (both listing ids stay in `sources[]`); inventory can be undercounted. Request: pass the
`RawListing` (or `source`, `fetched_at`) to `is_duplicate`.

**Install the spine for these tests** (read-only, nothing merged):
```bash
git archive 99e9ec0 | tar -x -C /tmp/mbos-99e9ec0 && .venv/bin/pip install "/tmp/mbos-99e9ec0[dev]"
```
`tests/test_spine_seam.py` skips if `mbos` is not importable. It uses a pinned test copy of 01's contracts
(`tests/fixtures/mbos_contracts_99e9ec0/`) as `MBOS_CONTRACTS_DIR`, and pgserver for PostgreSQL 16.

## 10. Credential-free official sources — READY_QUEUE B-03

| | GSA Auctions (`adapters/gsa_auctions.py`) | Trash Nothing (`adapters/trashnothing.py`) |
|---|---|---|
| Endpoint (FACT, from official OpenAPI, read 2026-10-07) | `GET https://api.gsa.gov/assets/gsaauctions/v2/auctions?format=JSON` | `GET https://trashnothing.com/api/v1.4/posts?types=offer&sources=groups,trashnothing&latitude&longitude&radius(m ≤ 80500)&per_page(≤100)&page` |
| Key | `GSA_API_KEY` (free, api.data.gov), sent as header `X-API-KEY` | `TRASHNOTHING_API_KEY`, query `api_key` (per spec); **redacted** from every recorded URL |
| Live switch | profile `live = true`; otherwise `config` error and zero requests | same |
| Identity / URL | `SaleNo-LotNo` / `ItemDescURL` (else `gsa-auctions://sale/lot`, never a guessed web URL) | `post_id` / `url` (else `trashnothing://post/<id>`) |
| Mapping | `auction_lot`; `HighBidAmount` > 0 → `auction_current`, else `starting_bid` (no amount); `buyer_premium_pct: 0`; `BiddersCount` → `bid_count`; LotInfo by `LotSequence` → description; zip+4 → 5-digit | `free_item`, price `{0, free}`; `OFFER:` prefix and `(place)` suffix stripped; lat/lng → `geo_tier`; `outcome` set → `gone`; `wanted` posts quarantined |
| Geography | no API geo filter → client-side `states` (default AR + neighbours) | API radius around Conway |
| Kept out of the Item (raw only) | contracting officer name/email/phone | `user_id`, `footer`, photos |

- **INFERENCE (GSA):** `AucEndDt` is a date only, so `ends_at` is set to `T23:59:59Z` as an upper bound. The real close also depends on `InactivityTime`. RESEARCH must confirm the time before any bid recommendation.
- **UNKNOWN until the first live call:** the exact JSON types of `LotNo`, `PropertyZip` and amounts. The adapters accept numbers or strings. The fixtures are hand-built from the documented schemas, not recorded.
- **Policy note for Michael (RECOMMENDATION; not decided here):** Trash Nothing offers are gifts from community groups, and some groups' rules forbid taking items to resell. Trash Nothing's Terms restrict redistributing *content*, not reselling items. Discovery is read-only either way. Every Trash Nothing Item carries `needs_review`, and whether to pursue free-item flips is listed as a business-policy question.
- The CLI's `--fixtures` now takes the fixture **root** (`tests/fixtures`, with `ebay/`, `gsa/` and `trashnothing/` subdirectories).

## 11. Freeze contract with lane E — READY_QUEUE B-04

The shared contract is in `docs/integration/freeze-request/`:
- `freeze-request.schema.json` (`mbos.discovery.freeze_request/1`)
- two example requests, which are the shared fixture
- a README with the exact mapping

Request flow:
- **Emit (02):** 2 consecutive 403/429, or 1 CAPTCHA, freezes the source locally (FROZEN). It then emits `{schema, level: L2, capability: discovery.source.<src>.read, source, reason, requested_at, requested_by: agent-02-opportunity, evidence{kind, status, consecutive_blocks}}`.
- **Apply (05):** `PanicStore.mutate("L2", capability, True, requested_by, reason)`, which is the same as `mbos-gov panic freeze --level L2 --target <capability> …`. Only a human releases it. Discovery never writes lane E's state.
- **Honour (02):** before every fetch, in both the pipeline and the spine adapter, discovery checks `PanicStore.read().blocks("agent-02-opportunity", capability, "discovery")`. Any reason means the source is skipped with zero requests. That covers L3, L1 on the agent, L2 exact, the L2 prefix `discovery.source.*`, the L2 category `discovery`, and an unreadable state. The check fails closed: a read error, or `MBOS_PANIC_STATE` set without `mbos_governance` installed, skips everything.

Verification (FACT): `tests/test_b04_freeze_contract.py` has 13 tests. They validate the emitted requests against the schema and check them field-for-field against the shared examples. They also round-trip through Agent 05's real `mbos_governance.panic.PanicStore`, installed read-only from `b632583`: apply blocks exactly that source, human release restores collection, broader freezes stop everything, and a missing state file fails closed.

Agent id is now `agent-02-opportunity`, the branch name, per R7 and 05's `policy.v1.json`. It was `agent-02-discovery`. This changes `provenance.agent_name` and `receipt_intent.actor.id`.

Install 05's package for these tests: `git archive b632583 | tar -x -C <dir> && .venv/bin/pip install --no-deps <dir>`. Without it, the real-store tests skip.

## 12. Sold-comps feed, lane-B side — READY_QUEUE C-04 (Agent 03 leads)

Hand-off agreed with Agent 03 (messages of 2026-10-07):
- **02 owns:** comp sources, raw retention, comp dedup, one Provenance record per comp, and the `candidate_comps()` pre-filter.
- **03 owns:** selection policy, bundle assembly and estimation (`mbos_economics.comps_feed.build_comps_bundle` / `research_step`).

| Piece | Where | Notes |
|---|---|---|
| `SoldComp.to_record()` | `comps.py` | `{comp_id, kind:"sold", price, currency, sold_date, source, source_comp_id, url, category, title, condition, fetched_at, raw_ref, provenance_id[, location, dom_days]}`, with `price` only. `condition: parts` is routed by 03 to `as_is_comps` |
| `ManualCompsAdapter` (`source = "manual"`) | `comps.py` | JSON inbox written by Michael or the Operator UI. Read-only. Provenance is `actor_type: human`, `human_actor`, `basis: FACT`. Works today. A human recording a price seen on a do-not-automate site is allowed, because nothing automates that site |
| `EbayInsightsAdapter` (`source = "ebay_marketplace_insights"`) | `adapters/ebay_insights.py` | Official but **Limited Release** (FACT, eBay docs). Runs only with `live=True` and an approved keyset with scope `buy.marketplace.insights`. Fixture-first. Provenance `actor_type: external`. The exact response shape is UNKNOWN until access is granted |
| `collect_comps()` | `comps.py` | Uses the same gate as discovery (`pipeline.gate`: policy → lane → local freeze → lane E PANIC). Identity is `(source, source_comp_id)`, so a human correcting a date or price keeps the `comp_id` |
| `candidate_comps(item, comps, as_of)` | `comps.py` | Deterministic pre-filter: same category, sold within (as_of − 365 d, as_of], title similarity ≥ 0.5. 03 narrows this to 90 days and checks vocabulary |

Source names match Agent 03's `comps_sources` registry exactly (`manual`, `ebay_marketplace_insights`). Any other name is refused by 03's fail-closed policy. Comps are evidence and never become Items.

**Acceptance (FACT):** `test_flip_with_comps_advances_to_scored_with_fact_comp_provenance` runs Agent 03's `research_step` (pinned @ `1044ed5`, engine 0.3.0; config now ships as package data).
- Input: the eBay-fixture 6x12 enclosed trailer, plus manual and Insights fixture comps.
- 7 candidates. 03 rejected 2 on vocabulary (5x8 and 7x14) and selected 5.
- Estimate status `estimated`, state moves RESEARCHING → **SCORED**, verdict **MAYBE**.
- Every selected comp's provenance is FACT and appears in `Item.research[]`.

## 13. Wake events — READY_QUEUE B-05 (lane-B producer for A-08 `notify_event`)

`src/mbos_discovery/events.py`:
- **Detect.** `WakeEventDetector.observe()` runs on every sighting, both in `SpineSourceAdapter.fetch` and in the standalone `run_discovery(events=…)`. It compares the sighting with that listing's last snapshot (identity is `(source, source_listing_id)`):
  - `price_change`: `price.amount` differs.
  - `new_info`: any other content field differs (status, title, description, bid count…). The changed fields are listed in the summary.
  - `auction_ending`: `ends_at` is within 24 h of the fetch and that end time hasn't been announced before. A listing already ending when first seen is not an event, because nothing changed.
- **Outbox.** Events wait in a durable JSON outbox keyed by an `event_id` content hash, so the same evidence is never queued twice.
- **Deliver.** `deliver_wake_events(engine, detector)` handles each pending event in turn:
  - It finds the Item by sighting identity (the same JSONB containment query `spine.ingest` uses).
  - It records the evidence's **Provenance first** (`basis: FACT`, source URI, `fetched_at`, `raw_ref`, `tool mbos_discovery.events`), then calls `mbos.workflows.notify_event(item_id, event, summary, evidence_provenance_id)`.
  - Events for Items not ingested yet stay pending. Delivery is at-least-once; a repeated notification is harmless, since nothing executes.
- **Why detection lives in lane B:** `spine.ingest` (correctly) treats a known identity as a no-op, so the spine never sees source-side changes. No spine change is needed. Agent 01 (A-04) can call `deliver_wake_events` as a step after `discover`.

Acceptance (FACT): `test_hold_wakes_on_lane_b_price_change_and_never_executes` runs Agent 01's real DBOS workflows @ `aa88e7a` on Postgres 16.
1. The eBay fixture trailer is discovered and goes to AWAITING_APPROVAL. Test-only illustrative economics, copied from 01's fixture, stand in for A-05.
2. HOLD with `wake_on=[price_change]` → HELD.
3. The source price drops from 950 to 800. Re-discovery is an identity no-op, and one `price_change` event is queued.
4. Delivery returns the item to AWAITING_APPROVAL, and an `APPROVAL_REQUESTED` receipt names the price change.
5. The evidence provenance is FACT by `agent-02-opportunity`. **No ACTION_EXECUTING or ACTION_EXECUTED receipt exists.** Re-delivery is a no-op.

Mutation check: with the `notify_event` call removed, the item stays HELD.

## 14. Saved-search alert e-mails — READY_QUEUE B-06 (ADR-02-0202 tier 2)

`src/mbos_discovery/adapters/email_alerts.py` has one adapter per origin: `govdeals_email`, `publicsurplus_email` and `estatesales_net_email`. Each is ALLOWED at tier 2. Scraping EstateSales.NET stays FORBIDDEN, and its email alerts are the sanctioned route.

- **Readers.**
  - `EmlDirReader`: fixtures or exported mail, no network.
  - `ImapReader`: runs only with `live=True` and a password from an env var. It opens the folder with `select(readonly=True)` (EXAMINE), searches `SINCE`, and fetches `(BODY.PEEK[])` so not even \Seen changes. The module contains no STORE, COPY, MOVE, EXPUNGE or APPEND.
- **Trust.**
  - Mail from other senders is skipped and never retained.
  - Mail that claims the origin's domain but lacks `dkim=pass` for that domain is quarantined, with raw kept for audit.
  - Only https links on the origin's domain whose path matches its listing pattern become listings.
  - Text goes through the usual injection flagging.
- **Replay.** The raw payload is `{origin, email_source, listing_index}` in MBOS-CJSON-1 form. `normalize` re-parses the message deterministically.
- **Mapping** (INFERENCE; generic parser). Nearby text gives:
  - the price: "Current/High Bid" → `auction_current`, "Starting at/Opening bid" → `starting_bid`
  - the end date: an end-of-day UTC upper bound, since alert times have no reliable timezone
  - the place: "City, ST [zip]"
- **Estate sales** are events, so they map to `other_asset`, subcategory `estate sale`, with `needs_review`. They are never keyword-classified.
- **UNKNOWN:** real alert layouts per origin. The fixtures are hand-built. Re-record real alerts on the first live run and tighten each parser.

## 15. SAM.gov Get Opportunities v2 — READY_QUEUE B-07 (service lane, `gov_contract`)

`src/mbos_discovery/adapters/samgov.py` targets the endpoint documented at open.gsa.gov (FACT): `GET https://api.sam.gov/opportunities/v2/search`.

- **Request.**
  - Parameters: `api_key` (query, per spec; **redacted** from every recorded URL), `postedFrom`/`postedTo` (MM/dd/yyyy, default 14-day lookback), `ptype=o,k,p,r`, `state`, `limit` ≤ 1000.
  - One call per configured state (default AR).
  - Runs only with `live=True` and `SAMGOV_API_KEY` set.
- **Mapping.**
  - Every lead is `type: service` and `opportunity_kind: gov_contract`.
  - The category comes from the NAICS table first (e.g. 811310 → `equipment_repair`, 238310 → `drywall_repair`, 5415xx → `technical_service`), then service keyword rules, else `other_service` with `needs_review`. The NAICS table is an INFERENCE fitted to Michael's service lines.
  - `responseDeadLine` → `ends_at` (UTC).
  - `price` is `quote_requested`.
  - The agency path becomes the counterparty name. `active` → `open` / `closed`.
  - The description summarises notice type, NAICS, solicitation number and set-aside.
- **Not fetched:** `description`, a link that needs the key. Points of contact stay in the raw artifact only.
- **Later:** `ptype=g` (sale of surplus property) could feed the flip lane. That's not part of this task.
- **Fixed while testing:** the smart-home keyword rules didn't match plurals ("thermostats", "doorbells"), so such leads fell to `handyman`. They now classify as `smart_home_install`.

## 16. ASKING comps from eBay Browse — READY_QUEUE B-08 (with Agent 03)

`comps.asking_comps_from_items(items)` turns listings discovery **already retained** into asking comps, so it makes no extra API calls.

- **Record:** `{kind: "asking", source: "ebay_browse", observed_date, price, currency, url, category, title, condition, fetched_at, raw_ref, provenance_id}`. There is **never** a `sold_date`, because an ask is not a sale.
- **Eligible listings:** active, fixed price, positive amount. Auctions (a bid is not an ask), free items and ended listings are excluded.
- **Provenance:** FACT, actor `external`, meaning only that "the source listed this asking price at `fetched_at`". The input is the sighting's `raw_ref`.
- **`candidate_comps` now excludes the subject's own listing**, by url or listing id, for every comp kind. An item's own ask can never be its evidence.

Acceptance (FACT, Agent 03 @ `e1869f2`, engine 0.6.1):
- **Asking-only evidence.** The asks are selected. Agent 03's round-one §14.1 design turns them into an **INFER** resale target, fenced so it can never act alone:
  - estimate `estimated` with a `no_sold_comps` gap
  - `yes_conditions.sold_comps_ok = false`, so YES is impossible
  - a PASS is `pass_on_priors`, so R13 keeps the item in RESEARCHING and it is never archived on an ask
  - research lines read "asking comp $X on <date>"

  My first assertion, that the estimate stays `insufficient`, was my assumption, not 03's design. I corrected it after 03 explained.
- **With SOLD comps added**, the item reaches SCORED and still carries the asking comp as kind `asking`.
- **History:** Agent 03's `entry()` used to raise KeyError `sold_date` on asking comps. I reported it, and 03 fixed it at `e1869f2` with my repro as a regression test.
- **Install note:** `research/agent-03-economics` commits a stale `economics/build/` tree (0.3.0). `git archive` gives every file the same mtime, so setuptools packages those stale files. Delete `economics/build` before `pip install`. Reported to Agent 03.

## 17. Discovery acceptance F1–F4 harness — READY_QUEUE B-10

To run it: `mbos-discover acceptance [--corpus tests/fixtures/corpus7d] [--out report.json]`. It is offline, uses the real adapters on fixture transports, and exits 1 on any failure. The code is in `src/mbos_discovery/acceptance.py`.

**Corpus.** `tools/make_corpus.py` generates it deterministically (seeded, byte-stable; a test regenerates and compares).
- Seven days across eBay Browse, GSA Auctions, GovDeals alert e-mails, the web form and referrals.
- 41 sightings of **36 physical objects**. `labels.json` holds the ground truth and is used only for scoring.
- Scenarios:
  - persistence and price drops
  - the same listing in two eBay queries
  - 3 eBay **relists** (same seller, new itemId after the original ended)
  - a pair of dealer **twin units** (two objects listed at once)
  - GSA lots re-polled daily
  - repeated GovDeals alerts
  - a customer using both web form and referral, and another submitting twice

**Result (FACT, this commit):**

| Check | Result |
|---|---|
| F1 | PASS: 36 Items, every sighting has a `raw_ref` whose bytes are retained and hash-verified |
| F2 | PASS: **missed-duplicate rate 0.00%** (target < 2%), **false merges 0**, 36 Items for 36 objects |
| F3 | PASS: 403 and 429 each produce exactly 1 schema-valid L2 freeze request after 2 fetches, then 0 requests |
| F4 | PASS: all 8 FORBIDDEN sources are refused before fetch even when "enabled"; no adapter allow-lists a forbidden host |

**How F2 was reached (honest record).** The first measurement was **7.69%**, all of it from the 3 relists. The original dedup rule never merged same-source listings. I added a **relist rule** (`dedup.is_relist`, used by `ItemStore.observe` with the current fetch's listing ids). It merges a new same-source listing id into an earlier one only when all of these hold:
- the earlier listing is **absent from the current fetch**, i.e. it ended
- the seller name is identical and non-empty
- the category is the same
- title similarity is ≥ 0.90
- the price is within ±15%
- the earlier listing was last seen ≤ 14 days ago

Twins can never merge, because both are present in the same fetch.

**Stated limitations.**
- **Known ambiguity**, pinned by a test: from listing data alone, a dealer's *second identical unit*, listed after the first ended, looks like a relist and merges. No data is lost, but inventory is undercounted. **B-11 resolves this when photos exist (§19).** It remains when there are no photos, or when the same stock photo is reused.
- **The corpus is synthetic.** Agent 01's original F2 target is a 7-day **live** sample, which still needs live credentials.
- **The spine path doesn't have the relist rule yet.** Its `Deduper` call carries no source or fetch context. That's queued as A-14 for Agent 01.

## 18. Freeze round trip on Postgres PANIC — READY_QUEUE B-09 (after E-02)

Since Agent 05's E-02 (`1c554cb`, ruling R5), PANIC state lives in lane D's `mbos.panic_state`.
- **Reading.** Discovery now reads it through `mbos_governance.PgPanicStore(dsn)` using a **read-only** login. `mbos-discover` takes `MBOS_PANIC_STATE=<DSN>`. The `blocks(...)` call and its reason codes are unchanged, and the check still fails closed.
- **Writing.** Agents have no PANIC write rights. Lane E's gateway applies discovery's side-channel freeze requests and records a `KILL_SWITCH_CHANGED` receipt in lane D's ledger.

Verified (FACT) by `tests/test_b09_pg_panic.py`, 8 tests on a throwaway PostgreSQL 16 cluster. The cluster uses Agent 04's canonical migrations 0000–0007 @ `14bd690` and real per-role logins, and calls Agent 05's real `ActionGateway`, `PgPanicStore` and `apply_side_channel` @ `1c554cb`. All of these are pinned test-only copies.
1. Two 429s produce a local freeze and one side-channel request.
2. `apply_side_channel` applies it, with a `KILL_SWITCH_CHANGED` receipt whose actor is `agent-02-opportunity`.
3. Discovery, reading through the reader login, skips exactly that source with zero requests, even after the *local* freeze is cleared. Other sources still run.
4. Agent self-release is refused. Michael's release restores collection.

Also tested:
- both shared examples
- an L2 `discovery.source.*` prefix, L1 on the agent and L3 global each stop all discovery
- an unreachable database fails closed (`PANIC_STATE_UNREADABLE`)
- the CLI builds `PgPanicStore` from the DSN

The B-04 tests that used the removed file-based `PanicStore` were retired in favour of these Postgres versions.

## 19. Image perceptual hashing — READY_QUEUE B-11

`src/mbos_discovery/images.py` uses Pillow, an optional `images` extra.
- **Hash.** A 64-bit DCT pHash: grayscale, 32×32, the 8×8 low-frequency DCT block compared against its median.
- **Verdicts.** `compare()` returns:
  - MATCH: ≤ 10 bits apart
  - DIFFERENT: ≥ 20 bits apart
  - INCONCLUSIVE: anything in between
  - NO_IMAGES: either side has no photos
- **Retention.** Images are fetched read-only through an injectable `ImageFetcher`; only fixtures are used in this task. They're retained content-addressed and fill the contract's `normalized.images` with sha256 refs. pHashes live in the store index and can always be recomputed from the artifacts. An image problem never breaks discovery.
- **Adapters.** eBay, GSA and Trash Nothing expose their image URLs as dedup-only hints.

How dedup uses photos. Photos can only add certainty; INCONCLUSIVE or no photos falls back to the listing-data rules.
- **Relist:** the listing-data rule plus photos that are **not DIFFERENT**. Different photos mean a different physical unit, never a relist.
- **Cross-source:** price and place must always agree. Then either title ≥ 0.85 **or** a photo MATCH is enough, which catches re-uploads with different wording. DIFFERENT photos veto a title match.

Acceptance (FACT). The corpus now includes the ambiguous case: a dealer's second identical unit listed after the first sold, with its own photo. It has 43 sightings of 38 objects.
- **`mbos-discover acceptance` with photos:** F2 0.00% missed, **0 false merges**, 38 Items for 38 objects.
- **Listing data alone:** **1 false merge**, the two dealer units. The harness reports this alongside.
- **Measured distances:** relist re-uploads (rescaled, cropped, posterized) are 2–6 bits apart; the two dealer units are 34; JPEG q60 recompression stays ≤ 10.

Limits (stated):
- The photos are synthetic, not real seller photos.
- A dealer reusing one stock photo for two units can't be told apart.
- The distance thresholds need tuning on real photos once B-12 (live runs) is unblocked.

## 20. Lane-B dedup on the spine path — READY_QUEUE B-13 (A-14 context @ agent-01 `a910ad9`)

`mbos_discovery.spine` now applies the same rules as the standalone store, through Agent 01's A-14 `Deduper.is_duplicate(existing_item, candidate, context)`:

| Piece | Why |
|---|---|
| `FetchLedger` | Records each fetch run's listing ids. The relist rule needs "the original is **absent** from the current fetch", but the spine ingests one record at a time. The normalizer copies the run's set into `match_hints["present_ids"]`, which DBOS checkpoints. If that set is unknown, no relist merge happens (a possible miss, never a false merge). |
| `PhashIndex` (persisted JSON) | Holds pHashes and last-seen time per `(source, listing id)`. The spine's Item body doesn't keep lane-B hints, so the Deduper looks *existing* Items up here. |
| `SpineNormalizer` | Fills `NormalizedListing.match_hints` with `present_ids`, `phash` and `contact_fp`. |
| `SpineDeduper` | Service: contact-fingerprint bucket, existing Item not terminal. Flip with an existing same-source sighting: relist only (original absent, ≤ 14 d, same seller, title ≥ 0.90, price ±15%, photos not DIFFERENT). Flip from another source: cross-source rule (price + place, then title ≥ 0.85 or photo MATCH; DIFFERENT vetoes). |

**Blocking key changed (FACT, found by this task).** The spine only consults the Deduper for Items with an equal `dedup_key`. The old key contained a price band, so a relist that dropped from $1,627 to $1,497 crossed the 1500 band and was never compared. The measured result was a 2.56% miss on the spine path. The standalone store never blocks, so B-10/B-11 couldn't see this. The flip key is now `category|state` (falling back to zip prefix, then a 1° cell), with price and exact place judged inside the Deduper.

**F2 metric fixed.** Missed duplicates are now Σ over objects of (Items showing that object − 1), divided by Items. The old formula, (Items − objects) / Items, let a false merge offset a miss and could go negative (−2.7% was observed). Earlier reported values stand, because their false-merge count was 0.

**Acceptance (FACT).** `tests/test_b13_spine_dedup.py` drives the 7-day corpus through Agent 01's real `mbos.spine.ingest` on PostgreSQL 16:
- with photos: **F2 0.00% missed, 0 false merges, 38 Items / 38 objects**
- without photos: 0.00% missed and exactly the one known-ambiguous false merge
- `spine_d.ingest` (the lane-D backend) calls the Deduper identically. I verified that by reading the code @ `a910ad9` but did **not** run it here, since it needs lane D's schema at Agent 01's current pin.
- Not filled on the spine path: `normalized.images`. The photos are retained in lane B's raw store, but the spine's `mbos.artifacts` doesn't hold them. That would need a spine image-artifact hook (proposed).
