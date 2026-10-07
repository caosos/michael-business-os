# Receipt — READY_QUEUE B-19: one CLI for every source, plus `--dry`

- **Date:** 2026-10-07 · **Actor:** Agent 02 · **Task source:** Agent 01 dispatch (B-19, P1).
- **External effects:** none. The tests make the network (sockets, IMAP, HTTP transport) fail the test if touched.

## Acceptance — MET (FACT)
- `mbos-discover run --source <each> --fixtures` is green for every source, with the adapter-level results as expected. For example, CPSC gives 6 recalls, 3 entries and 3 review items; e-mail alerts give 2 Items; comps give added 6 and 3.
- `--dry` lists the exact requests, with keys redacted and the IMAP sequence read-only, and writes nothing.
- Without live flags or credentials, a real run makes zero network calls and reports "config".
- `tests/test_b19_cli.py`: 9 tests. Full suite after this change: **217 passed, 0 skipped**.
- The first-live-run checklist now starts with `--dry`; its "not in the CLI" gap is closed.
