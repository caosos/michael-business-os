# Receipt: D-18 (capital ledger)

- Timestamp: 2026-10-08T00:51:03Z
- Agent: 04
- Inputs (read-only):
  - `research/agent-01-coordinator` at `a704e84` / `c18cabc`: `mission.schema.json`, its examples, `mbos.mission.ledger_errors`, and the five technical rulings
  - `docs/product/DEAL_SNIFFER_START_HERE.md` §1 and ADR-0013
- Vendored byte-identical, with git blob ids in `state/tests/contracts-additive/README.md`: `mission.schema.json` and 3 examples.

## Built
`state/migrations/0017_capital_ledger.sql`, `state/tests/test_capital_ledger.py` (11 tests), and `docs/state/CAPITAL_LEDGER_DESIGN.md`. The new ID prefixes `cap_`, `msn_` and `mn_` are registered in `ids.py`.

## Acceptance (Agent 01's D-18 row) — all FACT
- **A closed flip returns principal and credits profit.** Two deploys on one item (acquisition plus repair) are both returned on close. The position goes from (500, earned 0, deployed 50) to (500, earned 80, deployed 0, available 580).
- **A loss reduces earned first.** A loss beyond earned becomes a flagged `principal_impairment`, while `protected_principal` stays 500. The document validates against the schema and the arithmetic invariants. The next profit repairs the impairment.
- **Replay from receipts reproduces the position.** `capital_verify()` compares the stored ledger with a replay from receipts alone. It passes on 10 entries, and it catches an entry edited behind the app's back (the chain itself is untouched).
- **Entries are insert-only and derived.** No role can insert, even the owner and a superuser (MB001). UPDATE, DELETE and TRUNCATE are refused. Every entry cites its source receipt and provenance.
- The position document matches Agent 01's `capital-ledger.example.json` for (500 funded, 30 deployed, 470 available).

## Also verified
- **Agents cannot mint capital.** A forged `capital_fund` receipt from `agent_write`, `gateway` or `policy_admin` is refused (42501). An agent session recording a "human" closing outcome is refused. Agent-reported closing outcomes move nothing and are counted.
- **A deploy over available is refused** and the budget commit and its receipt roll back; counts are unchanged.
- **Withdrawals come from earned only.** Anything above earned is refused.
- **One close per item**, and a non-closing outcome kind is ignored.
- **Mission:** UNKNOWN target and hours stay NULL, validated against the schema. Only the owner channel can set it, and a revision is a new row.
- Full suite: 240 passed, 1 skipped. The scratch DB upgraded 0016 → 0017 with the chain OK (191).

## Caught while building
Replay initially re-ran the insert-time role gate against the *replaying* session, so a read-only verifier was refused. The gate is now a flag the trigger sets and replay clears.

## Flags for Agent 01
1. **Profit after an impairment repairs it first.** The invariant "impairment only while earned is 0" leaves it no other place to go. Michael's rebuild decision is an explicit `fund`. Please confirm this is the intent.
2. A closing outcome counts only if a **human** recorded it (`actor.type` human, written from an approver-role session). The State MCP agent profile cannot move capital.
3. New ID prefixes: `cap_`, `msn_` (and `mn_` from D-17).
