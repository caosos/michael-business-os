# Receipt: D-16 (card enrichment inputs on lane D) + tmpfs housekeeping

- Timestamp: 2026-10-07T21:28:10Z
- Agent: 04
- Inputs: READY_QUEUE D-16 and ADR-0011, plus `spine_d.record_enrichment` at `research/agent-01-coordinator @ c4f0156` (read-only).

## D-16
- **Confirmed:** the UI and reader roles can read enrichment artifact content, and lane agents can patch `research` (see `docs/state/CARD_INPUTS.md`).
- **Found:** the read-modify-write pattern used by `record_enrichment` loses entries under concurrent enrichment. Reproduced on lane D: 2 concurrent lanes → 1 entry survives.
- **Built (migration `0015_card_inputs.sql`):**
  - `mbos.append_item_research`: an atomic append (lock, then read, then write), replay-safe and receipted
  - `mbos.v_item_card_inputs`: the UI view
  - `mbos.try_jsonb`
- **Results:** `pytest` 198 passed, twice. The new tests cover:
  - the UI and reader roles reading the view and the raw artifact
  - role boundaries
  - a demonstration of the hazard, and 12 concurrent appends that all survive
  - latest-per-block, malformed and missing artifacts, and replay and validation

## Housekeeping (Agent 01's request)
- `/run/user/1001` was 100% full. I removed my 3 leftover `d13-*` directories (about 186 MB) and my old `mbos-dev` socket dir. No Postgres was using them.
- Source: my D-13 reproduction script, which put its throwaway pgserver data under `$XDG_RUNTIME_DIR`. That script was scratch-only and is not in the repo.
- `a07pg` (Agent 07's, 38 MB) was left alone, since it is not mine.
- Result: the tmpfs is at 3%. The repo's own harness is clean: `tests/conftest.py` keeps the data under `/tmp` and removes it on teardown, and only a short socket dir goes under `$XDG_RUNTIME_DIR`. After a full run nothing of mine remained in `/run/user/1001` or `/tmp`.
