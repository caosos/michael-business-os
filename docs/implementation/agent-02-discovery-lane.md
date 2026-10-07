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
