# Agent Status

Agent: 02
Role: Discovery / Source Adapters (DISCOVER + NORMALIZE lane)
Branch: research/agent-02-opportunity
Worktree: /home/michaelos/business-os-worktrees/agent-02-opportunity
State: WAITING
Waiting on: queue refill from Agent 01 (no READY task for 02/lane B/ANY in READY_QUEUE @ 4950570; B-01..B-10 all DONE)
Done: B-01 @ 7c9da45
Done: B-02 @ cadfdae
Done: B-03 @ 8ff5476
Done: B-04 @ 029356c (lane-E half by Agent 05 @ d3b9948: fixture vendored, auto-apply of valid requests)
Done: B-05 @ e439b9b (HOLD wake_on=price_change wakes from a 02 fixture re-sighting on the real DBOS workflow; never executes)
Done: B-06 @ bd899f4 (GovDeals/PublicSurplus/EstateSales.NET alert e-mails; read-only IMAP; DKIM-checked; 137 tests)
Done: B-07 @ 32c148c (SAM.gov gov_contract leads, NAICS mapping, key redacted; 142 tests)
Done: B-08 @ be0dd52 (asking comps; vs Agent 03 @ e1869f2: INFER-only, fenced — no YES, pass_on_priors; 146 tests)
Done: B-10 @ e439d04 (F1-F4 harness green; F2 missed-duplicate rate 0.00%, false merges 0, 36 Items/36 objects)
Done: B-09 @ b12bdbd (freeze round trip on lanes D/E Postgres PANIC; 156 tests)
Done: C-04 (support, source side) @ a1a7730 (lead Agent 03 C-04 @ 882c726)
Current phase: Round Two — B-01..B-10 DONE; WAITING for queue refill
Started: 2026-10-06 (Round One) · Round Two started 2026-10-07
Last updated: 2026-10-07

## Current objective
**Claimed task (2026-10-07):** implement `SourceAdapter` / `Normalizer` / `Deduper` against Agent 01's
`mbos.interfaces` (agent-01-coordinator @ bed7609), with `raw_ref` = hash of the stored raw bytes in both lanes,
and route `FetchResult.error` / `freeze_requests` to a side channel (R5). Confirmed by Agent 01's `READY_QUEUE.md` /
`ACTIVE_WORK.md` @ `99e9ec0` (B-01 CLAIMED → 02). Next per queue: B-02 (ADR-0010 hashing), then B-03.

B-01 result (FACT): `mbos_discovery.spine` implements SourceAdapter/Normalizer/Deduper; 02 fixtures run through the
real `mbos.spine.ingest` on Postgres 16 with identity-first dedup; raw_ref bytes identical in both lanes; 68 tests.
Receipt: docs/receipts/2026-10-07-b01-spine-seam.md.
B-02 result (FACT): interop_check row 02 = 10/10 CONFORMS @ cadfdae; 89 tests. Receipt: docs/receipts/2026-10-07-b02-adr0010-hashing.md.
B-03 result (FACT): GSA Auctions + Trash Nothing adapters, fixture-first, `live = true` required for any real call,
keys never in provenance; 101 tests. Receipt: docs/receipts/2026-10-07-b03-gsa-trashnothing.md.
B-04 result (FACT): shared freeze contract docs/integration/freeze-request/ (schema + examples); discovery honours lane E
PANIC L1/L2/L3 fail-closed; round trip through Agent 05's real PanicStore @ b632583; 114 tests, 0 skipped.
Receipt: docs/receipts/2026-10-07-b04-freeze-contract.md. Agent id aligned to `agent-02-opportunity` (R7).
C-04 support result (FACT): manual + eBay Marketplace Insights comp sources, SoldComp hand-off agreed with Agent 03;
02 fixture trailer + comps → 03 research_step @ 882c726 → SCORED (MAYBE), FACT comp provenance; 122 tests.
Receipt: docs/receipts/2026-10-07-c04-comps-source-side.md.
Heads-up from 05: E-02 moves PANIC to Postgres (04 migration 0007); `MBOS_PANIC_STATE` becomes a DSN and the store
constructor changes; `blocks(...)` signature/codes unchanged. 02 adapts its CLI wiring when 05 announces it.

## Proposed tasks
- **P-02-6 (lane B, P2): image perceptual hashing.** This fixes the stated relist ambiguity (a second identical unit
  after the first ended) and cross-source photo re-uploads. Images get downloaded into the artifact store as sha256
  refs, which also fills `normalized.images`.
- **P-02-7 (lane B, P2, needs Michael #8 / credentials): live smoke runs.** eBay Browse, GSA, Trash Nothing,
  SAM.gov and IMAP, behind their `live` flags. Each run records real fixtures and re-checks the field mappings marked
  UNKNOWN, and starts the live 7-day F2 sample.
(P-02-1..P-02-5 were triaged by Agent 01 into B-05..B-09 @ aa88e7a; Michael questions became MICHAEL_DECISIONS #7, #8; Deduper gap = A-14.)
- **P-02-1 (lane B, P1): wake events for A-08.** Discovery emits `{kind: price_change | auction_ending | new_info,
  item_id, source, evidence provenance_id}` when a re-poll UPDATES an Item (price change, status change) or an auction
  crosses `ending_soon`. These are the lane-B producer for A-08's `_approval_gate` `wake_on`. The data already exists:
  UPDATED events, `price_changed`, `ending_soon`.
- **P-02-2 (lane B, P2): IMAP saved-search alert ingestor** (ADR-02-0202 tier 2). Fixture-first parser for GovDeals,
  PublicSurplus and EstateSales.NET alert emails from our own inbox. This is the sanctioned path for no-API sources.
- **P-02-3 (lane B, P2): SAM.gov Opportunities API v2 adapter** (official; free key). Fixture-first, live flag, for
  `gov_contract` service leads.
- **P-02-4 (lanes B+C, P2): `ebay_browse` asking comps.** Emit active eBay listings as `kind: asking` comps under the
  name already in Agent 03's registry. They improve the market-depth inputs; they are never sold comps.
- **P-02-5 (lanes B+E, after E-02): Postgres PANIC wiring.** Re-point `mbos-discover`'s `MBOS_PANIC_STATE` to 05's
  Postgres-backed store (a DSN), with unchanged fail-closed behaviour.
- (follow-up, 02 + 05, after E-02) re-point `mbos-discover` PANIC wiring to 05's Postgres-backed store (DSN).
- (Michael, via Agent 01) enable eBay Marketplace Insights only after eBay grants Limited Release access; until then
  sold comps come from manual entry (source `manual`).
- (for Agent 01 / ADR-0009) `Deduper.is_duplicate` should receive the candidate's `RawListing` (at least `source`,
  `fetched_at`) so same-source look-alikes are never merged on the spine path. See implementation doc §9.

Wave one (done):
Read-only DISCOVER + NORMALIZE lane against frozen contracts v1.0.0 (agent-01-coordinator @ 1269405).

## Completed (FACT — verified by tests on this branch)
- Python package `src/mbos_discovery` (3.12; runtime dep: jsonschema). CLI `mbos-discover run|health|clear-freeze`.
- `SourceAdapter` abstraction: `fetch` (never raises) + pure `normalize`; no effector methods.
- Read-only HTTP boundary: GET to allow-listed hosts + POST only to OAuth token URLs; everything else refused.
- Raw retention: content-addressed immutable `raw_ref` stored *before* normalization; replay from raw tested.
- Normalization into Item v1 for **both** lanes; every Item/Provenance validated against vendored frozen contracts (hash-pinned).
- Dedup: intra-source identity, cross-source merge (flip), contact-fingerprint merge (service, 14-day window).
- Source health HEALTHY/DEGRADED/FROZEN; repeated 403/429 or any CAPTCHA → FROZEN + L2 `freeze_request`; human-only clear.
- Policy registry per ADR-02-0202: FORBIDDEN (Facebook, Nextdoor, Thumbtack/Angi sites, EstateSales.*) cannot run; gray-zone sources need explicit enablement; unknown sources fail closed.
- Adapters: **eBay Browse** (flip; live OAuth path + fixture mode on the same code), **service intake** (website form + referral inbox).
- Per-record provenance (source URI + fetched_at + tool@version + raw hash) and `receipt_intent`s with idempotency keys for Agent 04.
- 56 tests green incl. acceptance F1, F3, F4 and the five required proofs (sources[], raw_ref, determinism, no duplicates, safe failure).

## Files produced (Round Two)
- src/mbos_discovery/** · tests/** · config/discovery.example.toml · pyproject.toml
- docs/implementation/agent-02-discovery-lane.md — design, invariant→test map, raw→Item field mapping, raw_ref rule, hand-offs, contract gaps
- docs/runbooks/ebay-live-credentials.md — path to live eBay data
- docs/receipts/2026-10-07-round-two-wave-one.md

## Blockers
- Live eBay data needs an eBay developer keyset (EBAY_CLIENT_ID / EBAY_CLIENT_SECRET). Not a build blocker: fixture mode runs the identical code path. Steps in docs/runbooks/ebay-live-credentials.md.

## Needs Michael decision
- NEW (business policy, not blocking discovery): may the system pursue flips of FREE items offered in community
  gift groups (Trash Nothing / Freecycle-style)? Some groups' rules forbid reselling gifted items. Until decided,
  every Trash Nothing Item is flagged `needs_review`; discovery stays read-only. (Agent 01 to triage into MICHAEL_DECISIONS.)
- None new. (Unchanged: MICHAEL_DECISIONS #3 gray-zone sources; Craigslist/GovDeals/HiBid stay disabled.)
- Action item (not a decision): create the free eBay developer keyset per the runbook.

## Needs coordinator review (Agent 01)
- Contract gaps (docs/implementation §6): make `sources[].raw_ref` required in v1.1; add an `ITEM_UPDATED`-type receipt event for merges/source-side updates; receipt type for source freezes (with 05).
- Hand-off shape for 04 (`events[].receipt_intent`, `raw/` layout) and 05 (`freeze_requests[]`).

## Unknowns
- eBay filter names / `distanceFromPickupLocation` behaviour on a live call (fixtures are hand-built from docs, not recorded).
- F2 duplicate rate on a 7-day live sample.
- Real items/day per source (gap request 02-(1)) — needs live runs.

## Next action
On credentials: live eBay smoke run, record a real fixture, tune the mapping. Otherwise next adapters in order:
GSA Auctions API → Trash Nothing API → IMAP alert ingestor → SAM.gov.
