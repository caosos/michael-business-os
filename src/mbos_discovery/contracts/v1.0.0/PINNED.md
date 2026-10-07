# Frozen contracts — vendored, do not edit

Verbatim copies of `docs/research/contracts/` from branch `research/agent-01-coordinator`
at commit `1269405` (contract freeze, ADR-0004, v1.0.0). Owner: Agent 01. Any change must
come from Agent 01 and be re-vendored here; Agent 02 never edits these files.

| file | sha256 |
|---|---|
| item.schema.json | c5a806f6ce98265dc697f53ec564b5c326d68d3eeed120d13c5caf2e40ee3ad4 |
| provenance.schema.json | 15db68a4c6ef28d442209cd35e45970330653e7dff76ce5431bd8b05ec807b4c |
| receipt.schema.json | c6a55d47583541aef839bc66f5ecf07dcca187d0325b64b380a3a1bf52f155f9 |
| vendor/agent-03/opportunity.schema.json | 0633bc58ae987e2b0596c343b404b8f982fcee7c6d02521d9bd311c268cf5797 |
| vendor/agent-03/scorecard.schema.json | a6718390616d3a0b29c6e4454a92c8e6efb54580d69f7b6716fb3841e17abb8d |
| vendor/agent-03/service-job.schema.json | 9e1fddc22fb50324999a4dda683d8268458a424bb462463a6933c3e5001d1506 |

`tests/test_contract_pin.py` fails if any byte drifts.

## canonical/ (ADR-0010, ACCEPTED) — vendored from agent-01-coordinator @ `99e9ec0`

| file | sha256 |
|---|---|
| ../canonical/mbos_canonical.py | da2745456f4ac1d1c6aa7a23350c76d65e9e06427422e23ebf9b9eb578799628 |
| ../canonical/vectors.json | 4ff072e400a8517af73b3d38062cf9538629b9adca14d35031bebab385069082 |
