# Receipt: A-38 one-command real dry-run environment

- **Task:** A-38 (P0), lane 01, branch `worker/a-38-bootstrap`. DRY-RUN only; no external contact.
- **Provenance:** lane D `origin/research/agent-04-state` @ 4a11f1b (`mbos_state.provision`), lane E `origin/research/agent-05-governance` @ 44a0fb2 (policy), lane F `origin/research/agent-06-communications` @ 3090e51, lanes 02/03/05 installed by `tools/sync_lanes.py` (02 @ 55a7e19, 03 @ 44e1beb, 05 @ 44a0fb2).
- **Change:** `tools/bootstrap_dev.py`; `mbos devdb up --lane-d`; `sync_lanes.py` also installs lane 02; RUNBOOK section; `tests/integration/test_bootstrap_dev.py` (real PG16: worker login lacks `approver`, owner login has it, owner URL only in `owner.env` 0600).
- **Verified by running it** on a fresh cluster (~7 s): `mbos worker --fixture fixtures/sources/illustrative.json` reports REAL for state store, governance, scoring, both enrichments and the planner; only `sources` is STAND-IN. `mbos decide` with the owner file reaches the database (unknown-AREQ error, not a permission error).
- **Two defects found by the real run and fixed (A-36 had never exercised them):**
  1. `production.py` imported `FileRawStore` from `mbos_discovery.store`; it lives in `mbos_discovery.rawstore` (worker crashed once `MBOS_RAW_DIR` was set).
  2. `LaneBEnricher` passed lane D's ISO-string `created_at` to lane B as `as_of`, which compares datetimes (every `item_lifecycle` ended in ERROR). It now parses to an aware datetime.
- **Open:** fixture items park at RESEARCHING (no comps in the fixture), so no decision card appears from the fixture alone. Needs a comps-bearing fixture or live source (not this task).
