# Receipt: F-02, lane 06 ADR-0010 conformance (MBOS-CJSON-1 / MBOS-RH-1)

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-02` (claimed in `4feb387`)
- **Intent:** make every hash lane 06 computes follow ADR-0010, and get interop row 06 to 10/10.
- **Effect:** this branch only. Read-only checks against the spine's database. No sends, spend or external calls.

## Provenance
| Input | Ref |
|---|---|
| ADR-0010, `contracts/canonical/` (py, sql, vectors, README) | `origin/research/agent-01-coordinator` @ `99e9ec0`. Copied with `git checkout <ref> -- docs/research/contracts/canonical`; `git diff --cached` against the ref was empty |
| Vendored module | `operator_ui/mbos_canonical.py` = `git show 99e9ec0:docs/research/contracts/canonical/mbos_canonical.py` (`cmp` identical) |
| Spine re-pin | `mbos` reinstalled from `git archive 99e9ec0` (it loads the same reference for every hash) |

## Verification (FACT)
- `python3 -I docs/research/contracts/canonical/mbos_canonical.py …/vectors.json`: all PASS, including `receipt_chain: 2 receipts verified`.
- `.venv/bin/python -m pytest -q tests -p no:cacheprovider` → `15 passed`. This includes the isolated-load interop emulation (10/10 cjson vectors, all rejections raise, RH-1 chain verifies) and the independent RH-1 verification of the real spine chain.
- The interop tool result is in the commit that sets `Done: F-02`. That run used Agent 01's `tools/interop_check.py`, with only row 06's path repointed to `operator_ui/mbos_canonical.py`.
