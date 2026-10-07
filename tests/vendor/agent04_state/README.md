# Vendored from Agent 04 (lane D) — TEST HARNESS ONLY

Source: `origin/research/agent-04-state` @ `14bd690` (`state/`), byte-identical, via `git show`.
Used only by `tests/conftest_pg` to build a real PostgreSQL 16 database with lane D's canonical schema
(migrations 0000-0007 + roles). Production never runs this copy: Agent 04 owns and migrates the DB.
Hashes: `MANIFEST.sha256` (checked by tests). Re-vendor on each 04 schema change.
