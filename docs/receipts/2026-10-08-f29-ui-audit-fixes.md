# Receipt — F-29 UI half of the operator audit (wave 2)

- Timestamp: 2026-10-08 · Agent: 06 Communications (bounded worker, Sonnet) · DRY-RUN: nothing sent, spent or published.
- Provenance: task row F-29 in `READY_QUEUE.md` (coordinator `cb55fe8`); findings F-88..F-100 from 07's `docs/qa/OPERATOR_AUDIT.md` (G-20). Built against `mbos` @ `cb55fe8` (A-40 `record_attestation`, mission legs with title/verdict/waiting_on) and `mbos_economics` 0.14.0 (C-25).

## What changed (FACT: see the diff and tests/test_f29_ui.py)
| Id | Change |
|---|---|
| F-88 | `operator_ui/__main__.py`: `owner_dsn()` reads `MBOS_OWNER_DATABASE_URL`; the old `MBOS_APPROVER_DATABASE_URL` still works with a stderr warning. `make_backend` sets `owner_login`; when False on lane D every page shows a red "Owner writes will be refused" notice (no silent fallback). |
| F-89 | The FROZEN banner explains the kill switch and names `mbos panic off --reason ...`. |
| F-90 | `attest_view.py`: a "Confirm" form per engine-requested, attestable evidence key (`ATTESTABLE`, minus already attested) -> `App.add_attestation` (CSRF + PIN, server-set author, key must be one requested) -> `SpineBackend.record_attestation` -> `spine_d.record_attestation` (D-29, owner channel). A service job no longer asks for a sold price first. |
| F-92 | Saved-comp message says the worker re-checks the inbox about once a minute; `mbos recheck` only if no worker runs. |
| F-94 | `/mission`: Job title, System says, Waiting on columns; HOLD wording; DEPLOY only when a leg is YES; stale ids show titles. |
| F-95 | `/digest` and `/summary`: "Priority score" (a plain number, not dollars) and "Expected profit" (dollars, with per hour) replace "Value $/h". |
| F-97 | `/wanted`: Edit form (new revision, same id, status and stop conditions kept); must-have and nice-to-have shown after saving. |
| F-98 | `/` starts with three lines: gap to target, cash available to deploy, best next move (UNKNOWN says what to set). |
| F-100 | Nav hides Source health, Usage and Audience previews when their source variable is not set. |

## Tests
See `docs/status/AGENT_STATUS.md` for the final counts. New: `tests/test_f29_ui.py` (17). Updated pins: comps message, lint wording, module list, `merch` examples and `MBOS_CONTRACTS_DIR` now read the pinned coordinator copy (`.tools/mbos-cb55fe8`), because the vendored mission/inventory schemas predate the new fields. The vendored frozen contracts were NOT modified.

## UNKNOWN / not done
- UNKNOWN: whether the lane D attestation path works end to end as the real `mbos_operator_ui` login in this UI (tests stub the backend call; `spine_d.record_attestation` is 01/04's, proven in D-29).
- The vendored `docs/research/contracts` copies of `mission.schema.json` and `inventory.schema.json` (+ inventory examples) are stale versus the coordinator; re-vendoring needs a separate step.
