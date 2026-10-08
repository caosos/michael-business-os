# Receipt: G-20 operator audit as Michael

- Action: ran the real dev assembly (`tools/bootstrap_dev.py`, `mbos worker`, Operator UI) from a detached worktree of coordinator `edda153` in `/tmp/a07audit/w`; drove every Michael job over HTTP. DRY-RUN only; nothing sent, spent or published; no other lane's branch touched; dev Postgres stopped afterwards.
- Provenance: observed output of the commands above (worker log, `mbos card/items/queue`, UI pages), lane pins 04 `4a11f1b`, 05 `44a0fb2`, 06 `3a30680`, 03 `44e1beb`, 02 `55a7e19`.
- Output: `docs/qa/OPERATOR_AUDIT.md` (jobs 1-7: 1 PASS, 2 FAIL, 4 PARTIAL; verdict: Michael cannot use it today). Findings F-88..F-101 (P0: F-88 UI reads the wrong owner DSN env var, F-90 no item can reach a decision).
- Health: `mbos_qa spine --rc` 105 passed / 0 failed (3 skipped); `mbos_qa card` 671 passed / 0 failed.
- State changed in the dev DB only (throwaway): mission, $500 fund, one Wanted campaign, three comps, `panic off`.
