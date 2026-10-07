Read-only copies of Agent 01 frozen contracts v1.0.0 (ADR-0004), taken from
`origin/research/agent-01-coordinator` @ acb6f3b for conformance tests only.
Agent 01 owns these files; do not edit here. The 03 economics schemas are NOT copied:
tests load them from `docs/research/schemas/` (this branch, v1.1.0).

`canonical/mbos_canonical.py` and `canonical/vectors.json` are byte-identical copies of `docs/research/contracts/canonical/` from `origin/research/agent-01-coordinator` @ `99e9ec0`. They are ADR-0010 MBOS-CJSON-1 / MBOS-RH-1 and are normative. `economics/src/mbos_economics/canonical.py` must begin with `mbos_canonical.py` byte-for-byte; `tests/test_adr0010.py` enforces this.
