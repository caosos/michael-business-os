# Receipt: Round two, wave one Action Gateway build (Agent 05)

- **Date:** 2026-10-07
- **Agent:** 05 (governance)
- **Branch:** `research/agent-05-governance`
- **External effects:** none. No network calls, sends, spend or deployment happened. The only effector is the dry-run effector.

## Inputs read (provenance)

All inputs came from `git fetch origin`, read-only through `git show`.

| What | Where | Commit |
|---|---|---|
| ADR-0004 unified contracts, ADR-0005 governance control plane, ADR-0008 Python | `origin/research/agent-01-coordinator:docs/decisions/` | `acb6f3b` |
| Integration plan (§5 ownership, §7 build paths, §8 acceptance, §10 gaps) | `…:docs/research/agent-01-integration.md` | `acb6f3b` |
| Frozen contracts v1.0.0: action-request, approval, receipt, provenance | `…:docs/research/contracts/` | `1269405` (copied byte for byte, sha256 values pinned in `src/mbos_governance/schemas/PROVENANCE.md`) |
| My Round-One design: §3–14, §17 acceptance tests | `docs/research/agent-05-governance.md` | `5ee191d` |

## What was checked and observed

- **FACT:** 114 passed (pytest 9.1.1, jsonschema 4.26.0, Python 3.12, venv outside the repo).
  - Command: `python -m pytest -q`.
  - Files: `tests/test_gateway.py`, `tests/test_policy_and_panic.py`, `tests/test_static.py`.
- **FACT:** the concurrency, crash and freeze-race tests were run 5 extra times. They passed every time.
- **FACT:** `python -I tools/check_no_bypass.py src` → PASS.
- **FACT:** `pip install .` followed by `mbos-gov panic status` with no state file prints FROZEN, `readable: false`, and exits with code 2.
- **FACT:** the frozen example `action-request-email-held.example.json` passes the schema. Its `payload_hash` is `sha256:00832c10…`. The payload recomputes to:
  - `sha256:c94d8a80…` with sorted keys and compact output
  - `sha256:0480a253…` with insertion order and compact output
  - `sha256:e4065a68…` with sorted keys and default separators

  None of these matches → reported to Agent 01 as ADR-05-003 R1.

## Map from the §17 acceptance tests to this build

| §17 | Covered in wave one | Test |
|---|---|---|
| 1 | n/a: autonomous drafting does not go through the gateway | (lane A) |
| 2 | yes, all 11 categories | `test_every_category_blocked_without_approval` |
| 3–8 | yes | YES, NO, HOLD, MODIFY, expired and bait-and-switch tests |
| 9–12 | yes | per-action, daily, 100-parallel and velocity tests |
| 13 | n/a in wave one: no delegation, so first contact is already tier 0 | — |
| 14 | yes, in the policy timezone; recipient-local time is UNKNOWN until Agent 06 delivers the consent ledger | `test_quiet_hours_refuses_sms_and_calls` |
| 15 | yes | `test_double_delivery_calls_effector_once` |
| 16 | partly: a stuck claim blocks any retry; the reconcile job is next | `test_crash_in_flight_is_never_blind_retried` |
| 17 | n/a: no live money effector exists | — |
| 18–20 | yes | L3, L2 and fail-closed tests |
| 21–23 | yes | capability-not-held, grant change, step-up |
| 24 | schema half: a tainted request is forced to tier 0. The INJECTION_SUSPECTED tripwire is next | `test_untrusted_input_forced_tier0_by_schema` |
| 25–26 | next: output secret scan | — |
| 27–28 | yes | `test_full_chain_reconstructable`, `test_tampering_detected` |
| A7 / A9 | yes | `assert_ledger_sound`, `test_unreadable_panic_state_fails_closed` |

## Confidence and uncertainty

- **High confidence:** the guard logic and the fail-closed paths. Each one has a test that tries to break it.
- **UNKNOWN:** how the Postgres swap will interact with the receipt chain. Agent 04's DDL computes `row_hash` in a trigger, while this build computes it in Python with the same formula.
