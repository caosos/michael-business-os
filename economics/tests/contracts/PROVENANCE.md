Read-only copies of Agent 01 frozen contracts v1.0.0 (ADR-0004), taken from
`origin/research/agent-01-coordinator` @ acb6f3b for conformance tests only.
Agent 01 owns these files; do not edit here. The 03 economics schemas are NOT copied:
tests load them from `docs/research/schemas/` (this branch, v1.1.0).

`canonical/mbos_canonical.py` and `canonical/vectors.json` are byte-identical copies of `docs/research/contracts/canonical/` from `origin/research/agent-01-coordinator` @ `99e9ec0`. They are ADR-0010 MBOS-CJSON-1 / MBOS-RH-1 and are normative. `economics/src/mbos_economics/canonical.py` must begin with `mbos_canonical.py` byte-for-byte; `tests/test_adr0010.py` enforces this.

`vendor/agent-03/*.schema.json` are Agent 01's vendored v1.0.0 copies from `99e9ec0`. They are byte-identical to Agent 03's round-one `b032676` (checked with `cmp`). Frozen Item v1.0.0 resolves them by their unversioned `$id`s. This branch's v1.1.0 schemas use versioned `$id`s (C-03).

`action-request.schema.json` and `outcome.schema.json` are byte-identical copies from agent-01 `aa88e7a` (frozen v1.0.0), for C-07 conformance tests.

`operator_profile.v1.json` is a byte-identical copy of agent-01 `config/operator_profile.v1.json` @ 24c4d3d (adds deal_classes + current_cash_context, ADR-0012; Michael's capabilities, owner-stated). Agent 01 owns it; do not edit here.
