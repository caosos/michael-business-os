# Agent Status

Agent: 02
Role: Discovery / Source Adapters (DISCOVER + NORMALIZE lane)
Branch: research/agent-02-opportunity
Worktree: /home/michaelos/business-os-worktrees/agent-02-opportunity
State: WORKING
Claimed: B-04
Done: B-01 @ 7c9da45
Done: B-02 @ cadfdae
Done: B-03 @ 8ff5476
Current phase: Round Two — B-01, B-02, B-03 DONE; working B-04 (source-health → L2 freeze request shape agreed with Agent 05; shared fixture)
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
Next: B-04 (E-01 DONE @ df826c3 → unblocked).

## Proposed tasks
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
