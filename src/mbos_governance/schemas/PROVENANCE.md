# Vendored contracts — provenance

These four files are byte-for-byte copies of the frozen v1.0.0 contracts (ADR-0004).

- Source: `origin/research/agent-01-coordinator` `docs/research/contracts/`
- Commit: `1269405` (contract freeze merged; branch head at copy time `acb6f3b`)
- Copied: 2026-10-07 by Agent 05

| File | sha256 |
|---|---|
| action-request.schema.json | 38be3f152c69b343bddc54edc0d86d29cc9f0b8c09250e66cd5f9f49304055b3 |
| approval.schema.json | d8593684adf1c622e7916f6e4aa068f73ff1bb38f62817f5606ce40e69072bc5 |
| provenance.schema.json | 15db68a4c6ef28d442209cd35e45970330653e7dff76ce5431bd8b05ec807b4c |
| receipt.schema.json | c6a55d47583541aef839bc66f5ecf07dcca187d0325b64b380a3a1bf52f155f9 |

`tests/test_contracts_pinned.py` fails if these drift from the hashes above. Changes go
through Agent 01 (semver bump), then are re-copied here.
