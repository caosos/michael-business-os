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

## 7. Not done in wave one (RECOMMENDATION order)
GSA Auctions API adapter → Trash Nothing API → IMAP alert ingestor → SAM.gov. Craigslist stays PENDING_MICHAEL. No Facebook / Nextdoor.

## 8. Run it
```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/mbos-discover run --config config/discovery.example.toml --fixtures tests/fixtures/ebay   # offline
EBAY_CLIENT_ID=... EBAY_CLIENT_SECRET=... .venv/bin/mbos-discover run --config config/discovery.example.toml  # live
.venv/bin/mbos-discover health
.venv/bin/mbos-discover clear-freeze ebay --by michael
```
