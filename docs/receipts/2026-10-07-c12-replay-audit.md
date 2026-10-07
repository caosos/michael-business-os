# Receipt: C-12, replay audit (AT-1 at scale) (Agent 03)

- **Date:** 2026-10-07
- **Task:** `C-12` (READY_QUEUE @ agent-01 `8c3e4fd`). Claimed at `8425ed9`. Code at `d5daf42` (package 0.8.0).
- **Scope:** read-only audit code. The lane-D export was produced in a **throwaway** PostgreSQL 16 cluster (pgserver wheel, scratch venv, socket under `$XDG_RUNTIME_DIR`), destroyed after the run.
  - No shared database, Agent 04 worktree or system package was touched.
  - Agent 04's code came from a read-only `git archive` of `research/agent-04-state` @ `7ef19ba`.

## What it does
`mbos_economics.replay_audit.audit(items, receipts=None)` (CLI: `python -m mbos_economics audit EXPORT.json`, exit 0 clean / 1 drift). For every scored Item:
1. Recomputes `inputs_hash` from the stored inputs and the stored `scoring_config_version`.
2. Loads that config version (current file or history) and checks its content hash against the scorecard's `config_hash`.
3. Re-runs the verdict. A mismatch is **drift** when the same engine version produced it, and an **engine_change** (reported, not failed) when an older engine did.
4. For same-engine scorecards, does a full **byte replay** (catches tampered numbers whose verdict is unchanged).
5. In **ledger mode** (receipts given), requires a `SCORE_RECORDED` receipt whose `payload_hash` equals the stored scorecard's MBOS-CJSON-1 hash, and whose `inputs_hash` matches.

`load_scored_items(conn)` reads Agent 04's `mbos.v_item_documents` / `mbos.v_receipt_documents` with SELECT only.

## A gap found and fixed during the work (FACT)
Agent 04 records `SCORE_RECORDED` with entity = **the item**, not the scorecard. My first matcher keyed on `scorecard_id`, so it reported 19 receipts "checked" while comparing none.
- Fixed: receipts are matched per item, and the scorecard is identified by `payload_hash`.
- A test now proves that removing one ledger receipt is detected.

## Acceptance evidence (FACT)
"Audit over 03's goldens + a lane-D DB export: zero drift, and a planted drift is detected":
- **Goldens:** 14 scorecards, 14 receipts matched, **0 drift**.
- **Lane-D export** (`economics/tests/fixtures/lane_d_export/export.json`):
  - 19 scored Items (14 goldens + 4 Agent 02 service leads + 02's trailer with sold comps), written through `StateStore` (`create_item` → `transition_item` → `update_item_doc` SCORE_RECORDED / RECOMMENDATION_RECORDED → SCORED → RECOMMENDED)
  - read back through 04's views; PostgreSQL 16.2; `verify_chain` ok over 127 receipts
  - Audit: **19/19 audited, 19/19 receipts matched, 0 drift, 0 engine changes.**
  - Postgres **reordered every key** (JSONB), yet every hash reproduces, which is MBOS-CJSON-1 doing its job.
- **Planted drifts, each detected with the right classification:**

  | Planted | Classified as |
  |---|---|
  | tampered number | `scorecard` + `receipt` |
  | tampered input | `inputs_hash` |
  | tampered decision | `decision` |
  | missing receipt | `receipt` |
  | unknown config version | `config_missing` |
  | config edited without a version bump | `config_edited` (19/19) |
  | older engine disagreeing | `engine_change` (reported, audit still ok) |

- **Read-only proven:** config and export file hashes are unchanged after an audit, and the loader is SELECT-only.
- **Suite:** 188 passed, 159 subtests (py3.12 + jsonschema); 188 OK, 8 skipped (py3.10 stdlib).

## How to re-run on a real database
`load_scored_items(conn)` with the read role, then `audit(items, receipts=receipts)`. Or export as in `economics/scripts/lane_d_export.py` and run the CLI.
