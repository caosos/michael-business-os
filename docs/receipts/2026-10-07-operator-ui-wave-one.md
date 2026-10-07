# Receipt: Operator UI wave-one build (Agent 06, lane F)

- **Date:** 2026-10-07
- **Actor:** Agent 06 (Claude Code, `research/agent-06-communications` worktree)
- **Intent:** build the minimal Operator UI approval surface (YES / NO / MODIFY / HOLD) against the frozen v1.0.0 contracts, with dry-run effectors only.
- **Effect:** code and docs committed to this branch only. No merge to main. No other agent's branch or worktree touched. No network calls from the code. **No SMS, email, voice or seller contact.**

## Provenance (inputs read)
| Input | Ref |
|---|---|
| Coordinator integration plan | `origin/research/agent-01-coordinator:docs/research/agent-01-integration.md` @ `acb6f3b` |
| ADR-0004 / 0005 / 0006 / 0008 | same branch, `docs/decisions/` |
| Frozen contracts v1.0.0 | same branch, `docs/research/contracts/`. Copied byte-identical into this branch (verified with `git diff --cached origin/research/agent-01-coordinator -- docs/research/contracts`, empty output) |
| Own approval-gate research | `docs/decisions/ADR-002-approval-gate-and-receipts.md`, `docs/research/agent-06-communications.md` §12–13 |
| Synthesis / owner decisions | `ROUND_ONE_SYNTHESIS.md`, `docs/status/MICHAEL_DECISIONS.md` (coordinator branch) |

## Verification (FACT)
- `python3 -I -m unittest discover -s tests -t .` → `Ran 29 tests … OK` on Python 3.10.12, using the built-in validator (jsonschema is not installed).
- Mutation check: disabling the payload-hash comparison in `approvals.py` makes `test_stale_hash_refused_and_nothing_written` fail. The file was restored afterwards.
- Live run: `python3 -m operator_ui serve --seed --port 8799` served `/` and `/api/queue.json`. A request with `Host: attacker.test` returned `403`.
- The example payload hash in `action-request-email-held.example.json` does not equal sha256 of the payload under any of 4 common JSON serializations. Example hashes are illustrative, so the canonicalization is specified in `operator_ui/util.py:canonical_json`.

## Outputs
- `operator_ui/` (package), `tests/test_operator_ui.py`
- `docs/research/agent-06-operator-ui.md` (spec, rule enforcement, seams, gaps)
- `docs/decisions/ADR-06-003-operator-ui-stdlib.md` (PROPOSED)
- `docs/status/AGENT_STATUS.md`
