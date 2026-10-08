# Lane 07 handoff: QA / end-to-end integration / manual-assist outputs (lane G)

- **Branch / head (pushed):** `research/agent-07-marketing` (head in the closeout reply). Worktree `/home/michaelos/business-os-worktrees/agent-07-marketing`.
- **Role and boundaries:** independent QA. Owns `qa/` (harness `qa/mbos_qa/`, tests `qa/tests/`, pins, vendored copies) and `docs/qa/`, `docs/receipts/*-G-*`. Reads other lanes' code only through pinned `git archive` installs. **Never** publishes, contacts, spends, or edits another lane's branch/worktree; every run is DRY-RUN. Findings go to the owning lane via Agent 01 as `F-nn` (id, FACT/INFER, owner, repro, recommendation) in `qa/mbos_qa/__main__.py` `FINDINGS`.
- **Completed:** G-01..G-11 (receipts `docs/receipts/2026-10-07-G-*.md`; heads in `docs/status/AGENT_STATUS.md`). Latest: G-12 (RC READY 105/0 at mbos 8ef8802; F-51..F-68 re-verified, 21 residual strict xfails), G-09 `580644e` (F-42..F-49 verified fixed), G-10 `3e33817` (ADR-0012), G-11 `285b75a` (product seams).
- **Outstanding:** none claimed. Proposed tasks P-07-1..18 are in AGENT_STATUS. Re-verify after each owner fix (below).
- **Blockers:** none. Peer fixes are tracked as open F-nn.

## Run commands (all from `qa/`, venv = repo `.venv`, Python 3.12)
```
cd qa
../.venv/bin/python -m mbos_qa install-pins     # installs mbos + mbos_governance from qa/impl_spine_PIN and qa/impl_lane_pins.json, verifies byte identity
../.venv/bin/python -m mbos_qa spine --rc       # RELEASE-CANDIDATE VERDICT. Expected: 105 passed, 3 skipped, 0 failed (READY, dry-run scope) -> docs/qa/RELEASE_CANDIDATE.md
../.venv/bin/python -m mbos_qa card             # card + ADR-0012 + engine + product seams. Expected: 436 passed, 0 failed (G-12) (xfails are open findings) -> docs/qa/CARD_ACCEPTANCE.md
../.venv/bin/python -m mbos_qa run              # mock suite + e2e fixtures, ~77 pass; writes docs/qa/ACCEPTANCE_REPORT.md
MBOS_QA_IMPL=mbos_qa.impl_spine:build MBOS_QA_STATE_BACKEND=lane_d MBOS_QA_GATEWAY_MODE=lane_e PYTHONPATH=. ../.venv/bin/python -m pytest -q tests/followup   # A-15 follow-up: 34 passed on lane D+E
```
Health proof = the first three. Each run starts throwaway PostgreSQL clusters under `/tmp/a07pg-*` (pgserver wheel; short paths, <107 bytes for the socket). If a run is killed: `rm -rf /tmp/a07pg-*`.

## Pins and vendored copies (re-pin = edit, then `install-pins`)
- `qa/impl_spine_PIN` = Agent 01 `mbos` **944f8e4** (G-14); `qa/impl_lane_pins.json`: 05 `716098e`, 04 `c97ba6b`, 03 engine `3eb358f` (C-23) (read only via `git archive` in `tests/engine`, never installed).
- `qa/ext/{card.schema.json,operator_profile.v1.json,PIN.json}`: byte copies from 01 (re-vendor: `git show origin/research/agent-01-coordinator:docs/research/contracts/card.schema.json > qa/ext/card.schema.json`, same for `config/operator_profile.v1.json`, then refresh the sha256 in `PIN.json`).
- `qa/contracts/` frozen v1.0.0 + canonical (pin-checked); `qa/ext/seams/` ADR-0013 examples copied from 01 (named `<dir>--<file>`, not frozen).
- Interfaces consumed: 01 `mbos` (spine, card, mission, campaign, valuation, merchandising), 04 lane D schema, 05 lane E gateway/policy, 03 engine. Provided: reports in `docs/qa/`, findings, the release-candidate verdict.

## Open findings, with owner and repro (G-12: F-51, F-54, F-57..F-60, F-63, F-64 FIXED; the rest of F-50..F-68 OPEN or PARTIAL, see `FINDING_STATUS`)
| ID | Owner | Repro (from `qa/`, `PYTHONPATH=.`) |
|---|---|---|
| F-50 | 01 gate | gate ignores a failed `git fetch` and extra non-.py/.json files in installs (01 said they will fix it). Repro: see receipt `2026-10-07-G-09-reverify-g08-fixes.md` |
| F-51..F-56 | 01 card | `../.venv/bin/python -m pytest -q tests/card/test_card_adr0012.py -rx` (strict xfails: cash context, NaN crash, negative cash/days, thresholds, liquidity, gross range) |
| F-57, F-58 | 03 (+01) | `../.venv/bin/python -m pytest -q tests/engine -rx` (item `current_cash` vs profile; no "wrong buy today" reason line) |
| F-59..F-62 | 01 merchandising | `../.venv/bin/python -m pytest -q tests/seams -rx -k "euphemisms or obfuscated or visible or label or downgrading or vanish or provenance or verification"` (F-59 is **P1**) |
| F-63..F-65 | 01 mission/campaign/valuation | `-k "non_finite or projection or coherent"` |
| F-66..F-68 | 01 campaign/valuation | `-k "expired or autopilot_limits or internally_consistent or appraisal"` |
| F-1..F-12, F-15, F-17 | 01/03/04/05 | round-one observations (contract gaps, mock limits, launcher git identity); status not re-verified since round one; see `FINDINGS` text |
When an owner fixes one: remove the strict xfail marker (do not loosen the assertion), set `FINDING_STATUS` to `FIXED (<task>)`, re-run the three health commands.

## Known pitfalls
- **Stale installs:** pip keeps old code under the same version string; always `install-pins` (it verifies bytes) before trusting a result.
- `qa/var/egress_policy.json` and `litellm_keys.json` are tracked but rewritten by every run: `git checkout -- qa/var` before committing.
- Never `pkill -f` a pattern that appears in your own command line (it kills your shell). `/run/user/1001` is a shared 1.5 GB tmpfs: never put clusters there.
- A gate/peer commit may exist only in the shared object store (G-09: 01's `100d2ed` before its push); verify identity with `git diff <a> <b> -- src tools tests`.
- Tests whose premise was overtaken by a peer design change were RESTATED with the reason in the docstring (F-23 no request on denial, R22/R24/R25, F-42 recovery via `recover_orphan_gates`, F-43 receipt on the item). Never weaken to make green.
- Gate fault-injection sandbox (`/tmp/a07gate`, outside the repo) is disposable; recipe is in the G-08/G-09 receipts (fake `origin/*` refs for 04/05, `--no-fetch`).

## Open questions
- Deal-class thresholds and `current_cash_context` are PROVISIONAL/Michael-owned (MICHAEL_DECISIONS #9, #10): UNKNOWN until he answers.
- Whether the engine's $40/h `pph_floor_ok` gate is in the spirit of ADR-0012 (I treated it as in scope): Agent 01.
