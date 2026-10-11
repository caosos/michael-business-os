# F-139: owner's earlier decision shown on /market cards (read-only, local)

**Provenance:** queue row F-139 (ADDED BY 01, owner request "make the system use what I gave it"); mbos `decision_cases` from `origin/research/agent-01-coordinator` (A-61/A-64/A-67), installed from `git archive` into `.tools/mbos-f139` (git-ignored).
Source/staging only. No live change, no release, no :8766 reload.

## What changed
- `operator_ui/precedent_view.py` (new, ~95 lines): for each CHECKED result card calls `mbos.decision_cases.propose({listing_id, source:'gsa', title, evidence:[]})`; renders a collapsed
  `<details>` "Your earlier decision on a similar listing (proposal, for your review)": precedent decision, reason summary, verified facts, YOUR ESTIMATES (labelled "estimates, not facts"),
  unverified evidence, uncertainty/missing evidence then, evidence kinds this listing lacks, shared words, and "about that ONE earlier listing, not a preference for a category".
- `operator_ui/market_view.py`: gallery and list cards get the block injected; unchecked-section cards get none. Filters, ranking, hiding, saves and learned prefs are not touched (no code path reads the result).
- Store state: absent/empty = nothing; disabled = one honest line; `INTEGRITY_FAILURE` = one honest line; any other error = nothing. Never a crash. Read only: nothing is written and no cache is fetched.
- Stored `amount_usd` on an owner estimate is deliberately NOT rendered (no amounts that could read as a bid/purchase hint). Free-text of the owner's own case is shown as the owner wrote it.
- The mbos default store path is computed from its install location (wrong when pip-installed), so the UI points `MBOS_DECISION_CASES_DIR` at `var/private/decision_cases` of this checkout for the call unless it is already set.

## Tests (SYNTHETIC cases only, `MBOS_DECISION_CASES_DIR` in tmp): `tests/test_market_f139.py` 8 passed
match shows collapsed block with estimates labelled (gallery and list); filters, result ids, counts and prefs file unchanged with vs without a store (page equal once the block is stripped);
no store / empty store show nothing; disabled and tampered store show exactly one honest line; a listing never matches itself; unchecked cards get no block.

## Screenshots: `docs/receipts/f139-precedent-screenshots/` (`tools/f139_precedent_shots.py`)
Desktop 1648x1000 and mobile 390x844: no store, synthetic store collapsed and expanded, synthetic disabled. `evidence.json` isolation proof: store dir in a temp dir outside the repo,
owner private store untouched (before/after listing equal), same known result ids with and without the store, loopback only, committed test fixture cache, SYNTHETIC data only.

## Environment note
Updating the installed mbos to a build that has `decision_cases` needs `setup.py` + `docs/research/contracts` in the extracted tree (else packaged `_data/config` is missing and intake/assets tests fail); done.

## Health
See AGENT_STATUS for the numbers of the final `tools/run_tests.sh`.

Final run: reference 436 passed / 1 failed (known `test_resale_f39`; one extra failure was the module allowlist in `test_operator_ui.py`, fixed); lane D+E 104 passed / 3 failed (2 known F-32 + `test_wanted_f25` order flake, passes alone 9/9). Focused f139: 8 passed.
