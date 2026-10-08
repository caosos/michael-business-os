# Lane 02 handoff (Discovery / source adapters, DISCOVER + NORMALIZE)

- **Branch / head (pushed):** `research/agent-02-opportunity`. The head is the commit that adds this file; see `git log -1`. The last code commit is `d4e8670` (B-20). 267 tests pass, 0 skipped.
- **Role and boundaries:** Read-only discovery. Owns:
  - source adapters
  - raw retention (`raw_ref`)
  - normalization to Item v1
  - dedup (identity, relist, cross-source, photo pHash)
  - source health and block freezes
  - evidence for the card (listing_activity, seller, category_tags)
  - sold and asking comps
  - CPSC and NHTSA knowledge entries
  - the campaign matcher
  - Never: contact anyone, bid, buy, post or message. Never edit the frozen contracts, another lane's branch, or governance rules. Never automate the FORBIDDEN sources (Facebook, Nextdoor, Thumbtack/Angi/HomeAdvisor sites, EstateSales.*). Everything is **DRY-RUN**; nothing has made a live call.

## Completed
B-01 `7c9da45` spine seam · B-02 `cadfdae` ADR-0010 hashing · B-03 `8ff5476` GSA + Trash Nothing · B-04 `029356c` freeze contract · B-05 `e439b9b` wake events · B-06 `bd899f4` alert e-mails · B-07 `32c148c` SAM.gov · B-08 `be0dd52` asking comps · B-09 `b12bdbd` Postgres PANIC · B-10 `e439d04` F1–F4 harness · B-11 `8c634c9` pHash · B-13 `741dfd7` spine Deduper · B-14 `0dd506b` photos in artifact store · B-15 `09a755c` listing_activity + seller · B-16 `ab61f02` CPSC · B-17 `43de283` NHTSA · B-18 `bae240e` model years · B-19 `a9cd922` one CLI + `--dry` · B-20 `d4e8670` campaign matcher · B-21 `d6eec69` category tags · C-04 (support) `a1a7730` sold comps.
Receipts: `docs/receipts/2026-10-07-*.md`. Design record: `docs/implementation/agent-02-discovery-lane.md` (§1–§27).

## Outstanding
- **B-12 live smoke runs. BLOCKED** on MICHAEL_DECISIONS #8 (eBay Marketplace Insights, optional) and operator credentials. Acceptance: first live run confirms the UNKNOWN field names and limits, re-records fixtures, and starts the live 7-day F2 sample. Procedure: `docs/runbooks/first-live-run-checklist.md`.
- Proposed (no row in READY_QUEUE yet; in AGENT_STATUS "Proposed tasks"):
  - P-02-9 confirm what live sources expose
  - P-02-10 enrichment as a post-discover step (Agent 01's A-20)
  - P-02-12 recall review gate (ruled R23)
  - NHTSA service bulletins (downloaded files, not an API)
  - re-read real listings for year forms such as `'18` / `MY2018`

## Blockers
Michael: #8 and credentials (eBay keyset; GSA, Trash Nothing and SAM.gov keys; an alert mailbox) per `docs/status/OWNER_ACTIONS.md`. #7 (reselling free-group items) only changes how Trash Nothing Items are reviewed.

## Key files and entry points (`src/mbos_discovery/`)
- `adapter.py` (SourceAdapter ABC) · `adapters/*` (ebay_browse, ebay_insights, gsa_auctions, samgov, trashnothing, email_alerts, service_intake, cpsc_recalls, nhtsa)
- `pipeline.py` (`run_discovery`, `gate`) · `store.py` · `dedup.py` · `images.py` · `health.py` · `policy.py` (ADR-02-0202 registry)
- `spine.py` (adapters for Agent 01's spine: `discovery_components`, SpineDeduper, FetchLedger, PhashIndex) · `artifacts.py` · `events.py` (wake events)
- `enrichment.py` (listing_activity, seller, plus category_tags) · `tags.py` · `comps.py` · `recalls.py`, `vehicle_safety.py` · `campaigns.py`
- `runner.py` + `cli.py` (`mbos-discover run|health|clear-freeze|acceptance`) · `acceptance.py` · `tools/make_corpus.py`
- `contracts/` (vendored, hash-pinned) · `config/discovery.example.toml` (a profile for every source, all live flags off)

## Run commands
- Setup: `python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'` (jsonschema, pytest, Pillow). The spine tests also need the sibling packages installed, **from `git archive <sha>` with `build/` removed**: `mbos` (Agent 01), `mbos_economics` (03), `mbos_governance` (05). Pins: `51dbd51`, ≥ `0.11.1` (03), `1c554cb` (05); Agent 04 migrations are vendored in `tests/fixtures/agent04_state_14bd690`. Without them those tests skip, not fail.
- Health: `.venv/bin/python -m pytest -q` → **267 passed, 0 skipped** (~80 s).
- Offline all-sources run: `mbos-discover run --config config/discovery.example.toml --fixtures tests/fixtures`.
- See the requests without making them: `mbos-discover run --config config/discovery.example.toml --dry`.
- Acceptance F1–F4: `mbos-discover acceptance` → F1–F4 PASS, missed duplicates 0.00%, false merges 0 (synthetic corpus).

## Interfaces with other lanes
- **Consumes:**
  - Agent 01: `mbos.interfaces` (SourceAdapter/Normalizer/Deduper with A-14 context), `spine.ingest`, `record_enrichment`, `mbos.card`, `mbos.campaign`.
  - Agent 03: `mbos_economics.valueadd.load_kb` / `match_hits`, and `comps_feed.research_step`.
  - Agent 05: `PgPanicStore`, `apply_side_channel`.
  - Agent 04: `put_artifact`.
- **Provides:**
  - Items with `sources[]` and `raw_ref`.
  - Freeze requests: `docs/integration/freeze-request/` (shared schema and examples).
  - Comps: records plus FACT provenance.
  - KB entries plus a review list (R23).
  - Enrichment blocks.
  - Campaign matches.
- **Re-vendor:** schemas under `src/mbos_discovery/contracts/` are pinned by `tests/test_contract_pin.py`. Test copies of other lanes' files live in `tests/fixtures/` with a `PINNED` note (`mbos_contracts_99e9ec0` also holds `card` and `campaign` schemas). Update by copying from the new commit with `git show <sha>:<path>` and updating the pin.

## Known pitfalls
- **Stale `build/`** in a `git archive` of any lane makes pip install old code while reporting a new version: always `rm -rf <pkg>/build`, and check `__version__`.
- **`$XDG_RUNTIME_DIR` tmpfs fills up** from leftover Postgres test clusters. The test harness puts sockets under `/tmp`; clean only your own `mbos02-pg-*` and `m02-*`.
- **Fixtures are hand-built (ILLUSTRATIVE).** Only CPSC (guide v1.3) and NHTSA (live GET) shapes were confirmed against primary sources. eBay field names are from memory, as are GSA, Trash Nothing and SAM.gov types and the alert-e-mail layouts.
- **The blocking key is coarse** (`category|state`). The spine only asks the Deduper about equal keys, so a finer key silently misses relists (found in B-13).
- **The card validates strictly:** `seller.rating` must be numeric (a regression was caught in B-15 and fixed).
- **Text is untrusted:** a field with instruction-like text is excluded entirely (tags and campaigns), not just the flagged sentence.
- **KB entries:** ids must be unique (03 refuses duplicates), and numeric-only model names are refused. Per-year sources (NHTSA) must carry `years`.

- **Commit authorship:** every commit on this branch before this closeout is authored "Agent 07 Marketing", because the shared `.git/config` identity was overwritten by whichever agent launched last. Lane ownership is shown by the `agent 02:` prefix in each message. The correction of record is `docs/receipts/2026-10-07-provenance-correction-commit-authorship.md` on Agent 01's branch. New work should set identity per commit (`docs/COORDINATION.md`).

## Open questions (UNKNOWN)
- Live field names and limits: eBay `item_summary`, GSA/SAM.gov/Trash Nothing, CPSC rate limit, NHTSA terms. Who answers: the first live run (B-12).
- Real alert-e-mail layouts (GovDeals, PublicSurplus, EstateSales.NET). The first live mailbox answers.
- How real listings state model years (`'18`, `MY2018`, description-only). Real listing data answers; then Agent 03 extends the extraction.
- Whether road miles will be supplied by RESEARCH, so "within N miles" can be settled beyond ring 0 (Agent 03).
- Live duplicate rate (F2 target < 2%): the synthetic corpus gives 0.00%.
