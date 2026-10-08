# Receipt: P-06-19 (human outcome through the Operator UI role)

- Timestamp: 2026-10-08T04:14:06Z
- Agent: 04 (bounded worker, Opus)
- Inputs (read-only): `origin/research/agent-01-coordinator` READY_QUEUE row P-06-19 (Agent 01's ruling; found by 06 in P-06-18 @ `8572f10`); 0002/0003/0004/0017 of this branch.
- Mode: DRY-RUN. Throwaway pgserver PG16 databases only; nothing persistent, nothing contacted.

## Built
`state/migrations/0018_human_outcome_ui.sql` and `state/tests/test_human_outcome_ui.py` (6 tests).
- `approver` (login `mbos_operator_ui`) gets EXECUTE on `mbos.record_outcome`, INSERT on `mbos.outcomes`, and the
  `executed -> outcome_recorded` edge in `mbos.action_request_transitions` (it already had UPDATE (status)).
- `mbos.record_outcome` is replaced with 0003's body plus one guard: a session that is not an `agent_write` member must
  pass `actor {type: human, id: <non-empty>}`, else 42501. `agent_write` grants and behavior are unchanged.
- Capital: the 0017 derivation trigger is untouched, so close still needs an approver session AND a human actor.

## Acceptance — all FACT, connecting as the real login roles
- UI role (`session_user = mbos_operator_ui`) + human actor records an outcome; the executed action request moves to
  `outcome_recorded`; the receipt's actor is `{type: human, id: michael}`; an idempotent replay returns the same id.
- A closing human outcome via the UI role moves capital: (500 funded, 40 deployed) -> (500, earned 60, deployed 0,
  realized 60); `capital_verify()` OK.
- UI role + agent actor, system actor, or a human actor with a blank id: refused (42501), no outcome row written.
- `agent_write` unchanged: it still records agent and human-actor outcomes; it still cannot close capital (42501);
  `agent_write`/`gateway` still cannot `capital_fund`.
- `verify_chain` OK in every test.
- Health (`cd state && .venv/bin/python -m pytest`): **246 passed, 1 skipped** (was 240 + 6 new). The skip needs
  `MBOS_ECONOMICS_SRC`, as before.

## Notes (INFER)
- `mbos_dbos` is an `agent_write` member, so the guard does not bind it (ruling: keep `agent_write` as is). The UI
  must still run on `mbos_operator_ui` (P-06-12), where the guard applies.
- The database cannot tell two humans apart; the UI must pass the authenticated author as `actor.id` (unchanged pitfall).

## Next
06 flips its pinned P-06-18 finding (human outcome entry under the real UI role).
