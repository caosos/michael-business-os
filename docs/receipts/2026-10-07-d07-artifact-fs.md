# Receipt: D-07 (filesystem artifact store)

- Timestamp: 2026-10-07T17:48:06Z
- Agent: 04
- Task: READY_QUEUE D-07 (claim confirmed by Agent 01)

## Built
- `state/migrations/0009_artifact_fs.sql`:
  - `mbos.artifact_fs_path()`
  - a CHECK forcing an fs row's `location` to its canonical content-addressed path
  - `mbos.register_artifact()` (agent_write, gateway), which is idempotent and never replaces a row
- `state/mbos_state/artifacts.py`: `ArtifactStore`
  - `put`: atomic write + fsync, read-only file, then index
  - `get`: re-hashes and checks size; inline artifacts are read through the same API
  - `verify_all`: reports missing, modified and unindexed files
- CLI `verify-artifacts`. `backup-dump.sh` copies and verifies artifacts, and `restore-drill.sh --fresh-cluster` re-verifies them against the restored index.

## Results (FACT)
- `pytest`: 171 passed, twice. `tests/test_artifacts.py` covers:
  - round trip, layout, read-only mode, idempotency
  - tamper detection: modify, truncate, delete
  - a tampered file is never overwritten (kept as evidence)
  - unindexed files are reported
  - index rules: no arbitrary path, privileges, append-only
  - CLI against a backup copy, including detection of a swapped file
- Scratch DB upgraded to 0009 (receipted). Backup → fresh-cluster restore drill: 183 receipts verified (ADR-0010 reference) and 6 artifacts verified from the backup copy.
