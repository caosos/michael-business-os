# Receipt: F-03, comms dry-run spec as data

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-03` (claimed in `c125618`)
- **Intent:** turn 06's outstanding spec items (1)(3)(4)(6) into versioned data plus pure checks, with no sends.
- **Effect:** this branch only. No network, no provider accounts, no messages.

## Provenance
| Input | Ref |
|---|---|
| Round One comms research (legal FACTs, escalation triggers, guardrails) | `docs/research/agent-06-communications.md` §12–14, `docs/receipts/receipt-04-legal-compliance.md` |
| Gap list | integration doc §10, row 06 (`agent-01-coordinator` @ `bed7609`) |
| Category enums | `docs/research/contracts/item.schema.json` (frozen v1.0.0) |
| Hashing | `operator_ui/mbos_canonical.py` (ADR-0010 reference, byte-identical) |
| Quiet hours | ADR-0005 (20:00–08:00) |

Legal citations are restated from the Round One research receipts. They were not re-fetched in this task. UNKNOWNs are marked in the data files.

## Verification (FACT)
- `.venv/bin/python -m pytest -q tests -p no:cacheprovider` → `41 passed`: 26 F-03 tests plus the 15 F-01/F-02 tests, re-run green.
- `comms_spec.rehash()` computed 12 unique template hashes. A second run changes 0.
