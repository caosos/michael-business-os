# Receipt — READY_QUEUE B-14: lane B photos in the spine artifact store

- **Date:** 2026-10-07 · **Actor:** Agent 02 · **External effects:** none (fixtures, throwaway local Postgres).
- `artifacts.py`: `LaneDArtifactSink` (`mbos.put_artifact`) and `ReferenceSpineArtifactSink` (insert-only).
  - A photo is referenced in `normalized.images` only if the store returned exactly lane B's sha256.
  - On any failure the photo stays unreferenced.
- Acceptance "images round-trip by sha256 through the spine path": MET (FACT). `tests/test_b14_image_artifacts.py`, 4 passed:
  - corpus → real `spine.ingest` (reference DDL): every eBay Item's image refs resolve in `mbos.artifacts` with a matching sha256 and pHash; F2 still 0.00% / 0 false merges
  - no sink → no refs
  - lying or broken sink → no refs
  - lane D (Agent 04 @ 14bd690) `put_artifact` via `agent_write`: round trip and idempotent; the reader login is refused
- Full suite after this change: **175 passed, 0 skipped**.
