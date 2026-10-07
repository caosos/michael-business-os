# Release-gate hook: AT-1 replay audit (C-13, for Agent 01's A-02)

**Owner:** Agent 03 (lane C). **Consumer:** Agent 01's `tools/release_gate.sh`. **Package:** `mbos_economics` ≥ 0.8.1.

The audit re-derives every stored scorecard in a lane-D database. It is **read-only** (SELECT statements against Agent 04's `mbos.v_item_documents` and `mbos.v_receipt_documents`). The gate fails on any drift.

## The one command
Run it after `lane_d_e2e` has populated the database, and before teardown:

```bash
python -m mbos_economics audit --dsn "$MBOS_DSN"          # exit 0 = no drift, exit 1 = drift (gate fails)
```

- `$MBOS_DSN` is any psycopg DSN for the lane-D database. The read role is enough, for example `host=<sock> port=<port> dbname=<db> user=agent_read`.
- `psycopg` is needed only for `--dsn`; the package itself stays stdlib-only.
- With a file export instead (`{"items": [...], "receipts": [...]}`), run `python -m mbos_economics audit EXPORT.json`.

### Inside the Python e2e runner (no DSN plumbing)
```python
from mbos_economics.replay_audit import audit, load_scored_items
with engine.connect() as c:                                   # SQLAlchemy engine on the psycopg driver
    items, receipts = load_scored_items(c.connection.driver_connection)
rep = audit(items, receipts=receipts)
assert rep["ok"], [r for r in rep["rows"] if any(f["drift"] for f in r["findings"])]
```

## Exit codes
| Code | Meaning |
|---|---|
| 0 | Every scored Item replays: `inputs_hash`, config version and hash, and verdict all match. Same-engine scorecards replay byte-identically, and every scorecard has a ledger receipt. |
| 1 | At least one **drift**. The JSON lists the drifted rows with their `findings`. |
| 2 | Bad arguments (neither a file nor `--dsn`). |

## Expected output: clean export, receipts carry `payload_hash`
This is the real lane-D export written via Agent 04's StateStore (`economics/tests/fixtures/lane_d_export/export.json`):
```json
{
  "engine_version": "0.8.1",
  "items_seen": 19,
  "scorecards_audited": 19,
  "ledger_mode": true,
  "receipts_matched": 19,
  "strict": false,
  "drift_count": 0,
  "engine_change_count": 0,
  "weak_receipt_count": 0,
  "not_engine_count": 0,
  "ok": true,
  "report_hash": "sha256:5299b27ff1765bcd521293eb7f77cca91b4aa99d12d90d9bdc436e890e00eac1",
  "drift": [],
  "engine_changes": [],
  "weak_receipts": [],
  "not_engine": []
}
```
`report_hash` varies with the corpus and engine version. The gate should check `ok`, `drift_count` and the exit code only.

## Expected output on Agent 01's spine exports today: `weak_receipt_count > 0`, still exit 0
FACT (agent-01 `a910ad9`, `src/mbos/spine_d.py::record_score`): the spine's `SCORE_RECORDED` receipts carry `inputs_hash` but **no `payload_hash`**. The audit matches them on `inputs_hash` and reports a **weak binding**: the ledger proves *which inputs* were scored, but not *the scorecard content*. That is not drift, so the gate passes:

```json
{"ok": true, "scorecards_audited": 19, "receipts_matched": 19, "drift_count": 0, "weak_receipt_count": 19, "not_engine_count": 0}
```
(shown on the same 19 Items with `payload_hash` removed from the receipts, the way the spine writes them; exit 0)

- Add `--strict` to make weak bindings fail (exit 1). Enable it once the spine writes `payload_hash`.
- **Recommendation (proposed as P-03-06):** in `record_score`, add `payload_hash = sha256_of(scorecard)` (MBOS-CJSON-1, `mbos.hashing.reference`) to the `extra` of the SCORE_RECORDED receipt.

## Findings vocabulary
| Kind | Fails the gate | Meaning |
|---|---|---|
| `inputs_hash` | yes | The stored inputs (or the stored hash) changed after scoring |
| `config_edited` | yes | The config file for that version no longer has the content that scored it (edited without a bump) |
| `config_missing` | yes | The stored `scoring_config_version` cannot be loaded |
| `decision` | yes | Same engine version, different verdict |
| `scorecard` | yes | Same engine version, but byte replay differs (for example a tampered number) |
| `receipt` | yes | No SCORE_RECORDED receipt matches the scorecard, or the matched receipt has a different `inputs_hash` |
| `invalid_input` | yes | The stored inputs cannot be rebuilt or re-scored |
| `receipt_weak` | only with `--strict` | The receipt binds `inputs_hash` but carries no `payload_hash` |
| `engine_change` | no | An older engine version scored it, and today's engine reaches a different verdict (expected after a ruling; listed for review) |
| `not_engine_scorecard` | no | A card the engine never produced (for example the spine's missing-input fallback); nothing to replay |
