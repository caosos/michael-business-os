# Receipt: D-03 (reporting views + D1 restore drill)

- Timestamp: 2026-10-07T17:25:11Z
- Agent: 04 (lane D)
- Task: READY_QUEUE D-03, which depends on D-01 (done @ a0d1fbe)

## Actions
- `state/tests/test_views.py` covers every reporting view on a mixed flip/service history, plus reads by the read-only role.
- `docs/state/REPORTING_VIEWS.md` documents the views, their columns, semantics and example queries.
- `state/bootstrap/seed_demo.py` seeds a dry-run history entirely through the `mbos.*` API. Decisions in it are labelled SIMULATED.
- `state/bootstrap/restore-drill.sh --fresh-cluster` adds D1 against a new initdb with roles bootstrapped from scratch.

## Results (FACT)
- `pytest`: 138 passed.
- D1 on a seeded 179-receipt chain:
  - pg_dump, then restore into a brand-new cluster (port 55498, torn down afterwards)
  - `verify_chain` OK against the anchor, as `mbos_reader`
  - offline export verify: OK
  - ADR-0010 reference `verify_chain`: `(True, '179 receipts verified')`
- Caveat: "fresh host" was a fresh cluster on the same machine. A second machine is not available.
- Everything is dry-run only. No external calls. Clusters are stopped.
