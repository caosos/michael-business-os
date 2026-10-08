# Receipt: D-28 (G-18 F-85 + F-86: PANIC release and human outcomes are owner-only)

- Timestamp: 2026-10-08
- Agent: 04 (bounded worker, Sonnet)
- Inputs (read-only): queue row D-28; lane 07 repro `qa/tests/owner_channel/test_r14_g18.py` (`origin/research/agent-07-marketing`); migrations 0005, 0007, 0018.
- Mode: DRY-RUN. Throwaway pgserver PG16 clusters only.

## Built
- `state/migrations/0023_panic_owner_only_release.sql`
  - F-85: INSERT on `panic_state` revoked from agent_write/gateway/policy_admin/approver. `panic_set`, `panic_init`, `_panic_write` are SECURITY DEFINER (role checks moved to `session_user`); `panic_mutate` delegates. `_panic_write` EXECUTE revoked from all logins.
  - `append_receipt` refuses any receipt with entity_type `panic_state` or entity_id `panic:%` unless run as the table owner (i.e. inside the definer functions). Freeze-cancel receipts on action requests are unaffected.
  - `panic_require_receipt` now reads the receipt: a release (engage false, or a RUNNING global) needs a human receipt actor and an approver/mbos_owner session (policy_admin only for the first-revision init). ENGAGE stays open to gateway.
  - F-86: `record_outcome` with a human actor claim requires owner_channel/approver/mbos_owner for ANY session; agent_write may record agent/system outcomes only.
- Tests: new `state/tests/test_panic_owner_release.py` (real `mbos_dbos` + `mbos_operator_ui` via `provision()`); `test_agent_write_unchanged` updated (a human claim from agent_write is now refused, as D-28 requires).

## Acceptance
- FACT: as the real `mbos_dbos`: direct panic_state INSERT, the append_receipt+panic_seal route, `_panic_write`, and panic_set/panic_mutate release are all refused (42501); engage works; a forged human outcome is refused; an agent outcome is accepted. The owner login releases PANIC and records a human outcome; chain verifies.
- FACT: health `cd state && .venv/bin/python -m pytest`: 285 passed, 1 skipped, 0 failed.
- UNK: lane 07's own repro and 01's ACTION-path PANIC drill were not run here (they live on other branches); this lane's tests mirror the repro.

## Limits
- INFER: `panic_seal` stays granted (pure function, no write power once INSERT is gone).
