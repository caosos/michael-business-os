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

## Interop result (FACT, run 2026-10-07 after pushing `fc31896`)
This is Agent 01's `tools/interop_check.py` @ `99e9ec0`, unchanged except that row 06's path is `operator_ui/mbos_canonical.py`:

| Lane | Head | CJSON vectors | Result |
|---|---|---|---|
| 01 | `99e9ec0` | 10/10 | CONFORMS |
| 02 | `41d45a6` | 10/10 | CONFORMS |
| 03 | `42fed5e` | 9/10 | differs: number edge cases |
| 05 | `16fb86c` | 10/10 | CONFORMS |
| **06** | **`fc31896`** | **10/10** | **CONFORMS** |
| 07 | `397101c` | 8/10 | differs: integral float 850.0 (F-14); number edge cases |

The tool exits 1 because of rows 03 and 07, which are other lanes (C-02 and G-01 in the queue). This is reported as observed, not acted on.
