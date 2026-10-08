# Receipt: F-24 "My numbers" hardening (G-16 F-72..F-77) (DRY-RUN, owner channel)

- Agent: 06 Communications. Date: 2026-10-08. Task: F-24 (P1). Deps: F-22. Provenance: FACT, 07's G-16 findings and repros (agent-07 @ `9421d10`, `qa/tests/numbers/test_my_numbers_g16.py`), the capital-ledger SQL (agent-04 migration 0017).
- F-72: a fund/withdraw success message now echoes the amount read back from `mbos.capital_ledger` for the receipt. A replay (same nonce) is detected first by the receipt's idempotency key and reports "already submitted ... recorded as Fund of $X ... Nothing new was added"; the request's amount is never echoed.
- F-74: form pre-fill only blanks `None`; an explicit 0 shows as 0.
- F-73: `ux.same` compares UTF-8 bytes, so non-ASCII csrf/pin/nonce is a refusal page, never a TypeError (CSRF check, step-up on decisions, notes gate, numbers gate).
- F-75: strict amount grammar (ASCII digits, one optional `$`, commas only as correct thousands groups, at most 2 decimals).
- F-76 (ruling): per-transaction cap stays; `operator_ui/data/numbers_limits.v1.json` holds `max_total_funded_usd` (PROVISIONAL $5,000, Michael raises it by editing the file) and `confirm_fund_above_usd` ($2,000): a fund above it needs `FUND <amount>` typed in a confirmation box. Cumulative = ledger `protected_principal`.
- F-77: `ux.PinGate`: 5 consecutive wrong PINs lock every PIN check (numbers, notes, approvals) for 5 minutes, per process, in memory; the refusal text and a banner on /numbers show the lock and minutes left. A right PIN resets the count. Not persisted across restarts (UNKNOWN: restart clears the lock; acceptable on a loopback-only UI).
- Tests: `tests/lane_d/test_my_numbers_f24.py` (24 incl. parametrized). Health: reference backend 178 passed; lane D + lane E 91 passed; exit 0 · exit 0.
- No sends, spend, publish or credential change. 07's strict xfails flip in the next QA window (not re-run here: 07's harness lives on another branch).
