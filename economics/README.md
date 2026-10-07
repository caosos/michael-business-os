# mbos-economics: the deterministic economics and scoring engine (Agent 03, lane C)

This engine scores both lanes, FLIPS and SERVICES, as a pure function of `(Item v1, scoring config, scored_at)`. It works gates first and scores second. Its arithmetic is Decimal and replayable, and no LLM is involved anywhere. The design and the C14 resolution are in `docs/decisions/ADR-03-002-round-two-engine.md`. The worked numbers are in `docs/research/agent-03-worked-examples.md`.

## Layout
```
src/mbos_economics/config/scoring-config.json  current config (2026.10.1), the single source of every constant
src/mbos_economics/config/history/             superseded versions (replay loads them by version)
src/mbos_economics/config/estimation-priors.json  category priors for the estimator (own version; REC/UNK until LEARN)
src/mbos_economics/
  engine.py      compute() (pure scoring), score(), score_item() (adds ids, provenance, receipt drafts)
  lanes.py       flip and service ledgers + EV trees
  inputs.py      Item v1 -> engine input; strict validation (invalid input gets no scorecard)
  config.py      load / validate / version lookup / dump
  canonical.py   canonical JSON, sha256 content hashes, deterministic ULID-shaped ids
  replay.py      AT-1 / C22 replay
  comps.py       sold-comps aggregation (trimmed median, p25/p75)
  learn.py       Brier, MAPE, prior shrink, config-bump *proposal* (never self-activates)
  estimate.py    C-01 RESEARCH/estimate producer: Item (as discovered) + research bundle -> Item.economics
tests/                             118 tests: worked flips/services, AT-1..21, C22/C23, contracts, determinism, ADR-0010, C-01 estimator, C-04 comps feed
examples/*.scored.json             13 golden scored Items (regenerate with scripts/regen_examples.py)
```

## Use
```bash
cd economics
python3 -m unittest discover -s tests          # stdlib only; the contract tests skip without jsonschema
pip install -e '.[test]' && pytest -q          # full run, including Item v1 / Provenance conformance

PYTHONPATH=src python3 -m mbos_economics score  examples/smart_home_install.scored.json --scored-at 2026-10-07T12:00:00Z
PYTHONPATH=src python3 -m mbos_economics replay examples/trailer_utility.scored.json      # exit 0 = identical
```

```python
from mbos_economics.config import load_config
from mbos_economics.engine import score_item
out = score_item(item, load_config(), scored_at="2026-10-07T12:00:00Z")
# out["scores"]          -> Item.scores {scorecard_id, inputs_hash, scorecard}
# out["recommendation"]  -> Item.recommendation {verdict YES|MAYBE|PASS, rationale, ...}
# out["provenance"]      -> Provenance v1 record (tool + version + config + input hashes)
# out["receipt_drafts"]  -> SCORE_RECORDED / RECOMMENDATION_RECORDED for the 04 ledger (same txn)
```

## Rules this package keeps
- **No clock and no randomness.** `scored_at` is passed in. IDs and hashes are derived from it. A test greps the source for clock and random calls.
- **No hard-coded business numbers.** The $1,500, $800, $40, $65 and $75 values live in config, tagged `source: MICHAEL_DECISIONS`. Changing one means a version bump. The old file moves to `config/history/`.
- **Stdlib only at runtime.** Python ≥ 3.10. ADR-0008 targets 3.12; the suite also passes on 3.10.
- **Writes nothing.** Persisting results and receipts is the State lane's (04) job, in one transaction.

Config ships as **package data** (`mbos_economics/config/`). An installed wheel finds its scoring config, history and estimation priors without any `config_dir=` argument. `config_dir=` is only needed to point at a different config set.

## RESEARCH / estimate producer (C-01)
```python
from mbos_economics.estimate import estimate_item, apply_estimate
r = estimate_item(item, bundle, as_of="2026-10-07T18:00:00Z")   # pure; writes nothing
# r["status"]          "estimated" | "insufficient" (blocking gaps, e.g. no_comps, location_unknown)
# r["gaps"]            [{code, blocking, detail}]: what research should fetch next
# r["item_patch"]      economics + normalized.location.road_miles_one_way + research[] entries
# r["provenance"]      Provenance v1 (tool mbos_economics.estimate; derived_from = sources + every bundle item)
# r["receipt_draft"]   ITEM_UPDATED (ADR-0009; v1 fallback ITEM_STATE_CHANGED before == after)
scored = score_item(apply_estimate(item, r), cfg, as_of)
```
- **Inputs it reads.** Structured fields only. It never reads title or description text, so injected instructions cannot move a number.
- **Bundle provenance.** Every bundle element (comps, evidence, overrides, active-listing count) must carry a `provenance_id`.
- **No guessed resale.** A flip resale price is never guessed. With no comps the result is `insufficient`. Asking-only comps are discounted by the ask-to-sold ratio and can never reach YES.
- **Service quotes.** A service quote prices the whole job: materials, trip cash and all hours (labor, admin, travel, quoting) × `quote_rate_per_hour`. That rate is a **UNK placeholder** until Michael supplies a price list.

## Sold-comps feed (C-04)
```python
from mbos_economics.comps_feed import research_step, build_comps_bundle, load_fixture_comps
comps, prov = load_fixture_comps("tests/fixtures/comps/sold_comps.json")   # or Agent 02's mbos_discovery.comps adapters
r = research_step(item, comps, prov, as_of)   # comps -> bundle -> estimate -> score; persists nothing
# r["proposed_next_state"]  "SCORED" | "RESEARCHING"
# r["comps"]["rejected"]    every comp not used, with the rule that rejected it
# r["provenance_records"]   used comps (FACT) + estimate + score: persist with the transition
```
- **Ownership.** Agent 02 owns the sources (manual inbox; eBay Marketplace Insights, fixture-first), raw retention and comp de-duplication. Lane C owns selection.
- **A comp is used only when every check passes.** Selection is fail-closed and deterministic:
  - the source is ALLOWED (registry mirrors ADR-02-0202; unknown sources are refused)
  - the kind is one that source can report
  - same category
  - USD
  - sold within 90 days and not after `as_of`
  - FACT provenance with `source_uri` and `fetched_at`
  - no fixed-vocabulary conflict (type/size)
  - not a duplicate
- **Condition routing.** `parts` sales feed the as-is market median, never the resale target.
