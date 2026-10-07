# Receipt: Round-two economics engine build (Agent 03)

- **Date:** 2026-10-07
- **Actor:** Agent 03 (Economics / Scoring), branch `research/agent-03-economics`
- **Action class:** code and docs on this branch only.
  - No merge to main.
  - No other branch or worktree touched.
  - No external calls, purchases, messages or production systems.
  - No CAOSCare.

## Inputs (provenance)
| Input | Ref | How read |
|---|---|---|
| Own round-one research, schemas, config, ADR-001 | `research/agent-03-economics` @ `b032676` | working tree / `git show` |
| Coordinator integration plan, ADR-0004, INDEX (ADR-03-001 disposition), MICHAEL_DECISIONS, contracts v1.0.0 | `origin/research/agent-01-coordinator` @ `acb6f3b` | `git fetch origin` then `git show` (read-only) |
| Item v1 + Provenance v1 schemas | same @ `acb6f3b` | copied read-only to `economics/tests/contracts/` (see the PROVENANCE.md there) |

**FACT:** the vendored `contracts/vendor/agent-03/*.schema.json` were byte-identical to this branch's round-one schemas before the v1.1.0 edits (`diff` showed no output).

## Outputs
- `economics/`: the engine package (v0.1.0, stdlib-only), config 2026.10.1, the 2026.10.0 archive (byte-identical to `b032676`, checked with `cmp`), tests, 13 golden scored examples, and a CLI.
- `docs/research/schemas/*.schema.json`: v1.1.0. Additive and optional only; `$id` unchanged.
- `docs/decisions/ADR-03-002-round-two-engine.md` (PROPOSED).
- `docs/research/agent-03-worked-examples.md`.
- Errata header and AT-14 correction in `docs/research/agent-03-economics.md`; follow-up note in ADR-001.
- `docs/research/config/scoring-config.json` removed in favour of the single source (`docs/research/config/README.md` points to it).

## Verification performed
| Check | Command | Result |
|---|---|---|
| Full suite (pytest, py3.12, with jsonschema) | `pytest -q tests/` | 75 passed, 39 subtests passed |
| Stdlib only (py3.12) | `python3.12 -m unittest discover -s tests` | 75 OK (3 contract tests skipped: no jsonschema) |
| Stdlib only (py3.10) | `python3 -m unittest discover -s tests` | 75 OK (3 skipped) |
| Cross-version replay | 13 goldens generated on 3.12, replayed on 3.10 | 13/13 MATCH |
| Contract conformance | `tests/test_contracts.py` | every scored Item validates against Item v1; every provenance record validates against Provenance v1 |
| CLI | `python -m mbos_economics replay examples/trailer_utility.scored.json` | `match: true`, exit 0 |

## Method notes (INFERENCE / RECOMMENDATION)
- Arithmetic is Decimal with quantize-on-store. IDs and hashes are derived from inputs plus the caller's `scored_at`. Nothing reads the clock or randomness.
- The C14 resolution keeps the rule (a RECOMMENDATION, reasoned in ADR-03-002 §1).
- Coordinator defaults are config, tagged `source: MICHAEL_DECISIONS`. None of them is Michael-confirmed (UNKNOWN until he decides).

## Tooling
A Python 3.12 virtualenv with `pytest` and `jsonschema` was created in the session scratchpad. It is not in the repo and nothing was installed system-wide.

## Commit identity
The shared git config on this machine names "Agent 07 Marketing". Agent 03 left it unchanged, because the config is shared across worktrees. Round-two commits pass `-c user.name="Agent 03 Economics"` per commit.
