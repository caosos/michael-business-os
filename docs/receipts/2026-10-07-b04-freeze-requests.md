# Receipt: B-04, lane-E half (Agent 05)

- **Date:** 2026-10-07
- **Task:** B-04 (led by Agent 02; Agent 02's half DONE @ `029356c`)
- **External effects:** none.

## Inputs (provenance)
These were vendored byte for byte, with sha256 pinned in `tests/test_b04_freeze_requests.py`:
- Agent 02's contract at `origin/research/agent-02-opportunity` `docs/integration/freeze-request/`: the schema and 2 examples.
- `SideChannel` JSONL line shape: `{"kind":"freeze_request","freeze_request":{…}}`, from `src/mbos_discovery/spine.py`.

## Decision (Agent 02's ask 2)
**Lane E auto-applies valid freeze requests.** The gateway calls `engage_panic("L2", capability, actor=requested_by)`. The reasons:
- Engaging a freeze is always the safe direction.
- Discovery has already frozen the source locally.
- Under 0007, agents get no PANIC write rights, so the gateway must be the applier.

**Release stays human-only.** It needs a policy approver (`michael`), and a test checks this.

## Built
`src/mbos_governance/freeze_requests.py`: `problems`, `apply_freeze_request`, `apply_side_channel`. It has strict validation. A request is refused if:
- it fails the schema
- `capability` ≠ `discovery.source.<source>.read`
- it asks for a level other than L2
- it targets another lane
- it targets a `discovery.source.*` prefix
- it comes from any requester other than `agent-02-opportunity`

Re-applying a request is idempotent.

## Verification
- **FACT:** 12 B-04 tests pass. The full suite has 169 tests, and all pass.
- Both examples, once applied, block exactly their own source under lane B's honour check `blocks("agent-02-opportunity", cap, "discovery")`. They leave other sources clear.

## Note
- The tests run on the current PANIC store, which is the file-based one.
- E-02 moves PANIC into Postgres. The `read().blocks(...)` interface stays the same, so lane B's honour check does not change. Lane B's construction of the store changes when E-02 lands. I will tell Agent 02 then.
