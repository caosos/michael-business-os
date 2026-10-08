# Receipt: G-12, release-window re-run after A-32..A-34 (and C-23) (Agent 07, lane G, bounded worker)

- **Task:** G-12 (P1), queue row on `origin/research/agent-01-coordinator` (deps A-32, A-33, A-34 DONE; C-23 DONE @ `3eb358f`). DRY-RUN only: pure functions and throwaway PostgreSQL clusters; nothing published, contacted, sent or spent.
- **Stack (FACT):** `qa/impl_spine_PIN` = 01 `mbos` `8ef8802` (contains A-32 `54f3730`, A-33/A-34 `73aaec7`); 05 `716098e`, 04 `c97ba6b` unchanged; 03 engine re-pinned to `3eb358f` (C-23, `git archive` only). `install-pins`: byte-identical to the pins. Vendored `qa/ext/card.schema.json` and `operator_profile.v1.json` are byte-equal to 01 HEAD. The four `inventory/mower-view-*` seam examples were re-vendored: A-32 rewrote them to state the defect word for word.

## Results (FACT, commands from `qa/`)
| Command | Result |
|---|---|
| `python -m mbos_qa install-pins && python -m mbos_qa spine --rc` | **READY**: 105 passed, 3 skipped, 0 failed, 0 xfail -> `docs/qa/RELEASE_CANDIDATE.md` |
| `python -m mbos_qa card` | 436 passed, 0 failed -> `docs/qa/CARD_ACCEPTANCE.md` (card/engine/seams: 383 passed + 21 strict xfails) |
| `python -m mbos_qa run` | 77 passed, 0 failed, 1 known strict xfail -> `docs/qa/ACCEPTANCE_REPORT.md` |

## Strict xfails F-51..F-68
- **Flipped to passes (68 cases):** before any edit, the card run gave 68 strict XPASS failures. With the new example views those are real fixes. Markers were removed; assertions were not changed.
- **FIXED in full:** F-51, F-54 (A-34); F-57, F-58 (C-23); F-59, F-60 (A-32); F-63, F-64 (A-33).
- **PARTIAL, with the residual case still a strict xfail (21 cases).** These are residuals for owner 01, not regressions:
  - F-52: NaN days, NaN or string net, and 1e308 (crashes with a CanonicalError).
  - F-53: zero days and 1e-9 cash still get a class.
  - F-55: zero days-on-market is still shown as liquidity.
  - F-56: a value outside its low/high, and a negative cost.
  - F-61: a defect deleted from both the inventory and the view still lints clean.
  - F-62: a view may invent a `provenance_id`.
  - F-65: hours exceeded, inverted period, duplicate scorecard, stale ledger, DEPLOY while principal is impaired.
  - F-66: an autopilot whose limits have already expired still validates.
  - F-67: as_is above the after-repair values; medium confidence resting on priors only.
  - F-68: an evidence note saying "guaranteed"; null ranges not reconciled with `unknowns`.
  - `FINDING_STATUS` records each one as PARTIAL.
- **RESTATED (INFER: the premise was overtaken by a fix):** `test_the_late_season_mower_is_capital_intensive_and_ranks_low_today`. C-23 now refuses a per-item `current_cash`, so tight and loose cash are set through the profile-mirrored config `operator_context.current_cash` (`with_profile_cash`). The assertion is unchanged.
- **Two pre-flip spurious XPASSes (FACT):** with the old views, `test_a_view_cannot_invent_provenance_for_a_fact` passed only because the base view itself no longer linted. After re-vendoring it fails as before (F-62 residual).

## Acceptance
- RC READY 105/0: **met**.
- "Strict xfails for F-51..F-68 flipped to passes": **met for the fixed cases**. 21 cases across 10 findings remain open with the owner (REC: one follow-up 01 task, P-07-19).
