# mbos-economics: the deterministic economics and scoring engine (Agent 03, lane C)

This engine scores both lanes, FLIPS and SERVICES, as a pure function of `(Item v1, scoring config, scored_at)`. It works gates first and scores second. Its arithmetic is Decimal and replayable, and no LLM is involved anywhere. The design and the C14 resolution are in `docs/decisions/ADR-03-002-round-two-engine.md`. The worked numbers are in `docs/research/agent-03-worked-examples.md`.

## Layout
```
config/scoring-config.json        current config (2026.10.1), the single source of every constant
config/history/                    superseded versions (replay loads them by version)
src/mbos_economics/
  engine.py      compute() (pure scoring), score(), score_item() (adds ids, provenance, receipt drafts)
  lanes.py       flip and service ledgers + EV trees
  inputs.py      Item v1 -> engine input; strict validation (invalid input gets no scorecard)
  config.py      load / validate / version lookup / dump
  canonical.py   canonical JSON, sha256 content hashes, deterministic ULID-shaped ids
  replay.py      AT-1 / C22 replay
  comps.py       sold-comps aggregation (trimmed median, p25/p75)
  learn.py       Brier, MAPE, prior shrink, config-bump *proposal* (never self-activates)
tests/                             75 tests: worked flips/services, AT-1..21, C22/C23, contracts, determinism
examples/*.scored.json             13 golden scored Items (regenerate with scripts/regen_examples.py)
```

## Use
```bash
cd economics
python3 -m unittest discover -s tests          # stdlib only; the 3 contract tests skip without jsonschema
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

Path note: `CONFIG_DIR` resolves relative to the source tree (`economics/config`). When Agent 01 packages the platform, pass `config_dir=` explicitly.
