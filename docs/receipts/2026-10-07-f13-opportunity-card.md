# Receipt: F-13, Michael's opportunity card as the primary Operator UI view

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-13` (P0, Michael's request; claimed in `d697b3e`)
- **Intent:** render the ADR-0011 card at `/item/<id>`: header, listing activity, seller, WHY, economics, value-add plan, seasonality, transport, status timeline, RECOMMENDATION with step-up flag, the decision controls beneath it, the activity trail and the UNKNOWN list.
- **Effect:** this branch only. Read-only page plus the existing human-channel forms. No sends.

## Provenance
| Input | Ref |
|---|---|
| Spec | `docs/decisions/ADR-0011-opportunity-card.md`, `card.schema.json` @ `d2ef52f` (`card.schema.json` vendored byte-identical; `cmp` checked) |
| API | `mbos.card.load_inputs / enrichment_from_item / build_card / validate_card` @ `d2ef52f` (installed, not merged). No data model of my own |

## What was built
- `operator_ui/card_view.py`: pure rendering of the card dict. UNKNOWN shows as **UNKNOWN** with the card's reason; known values show their basis (FACT/INFERENCE/RECOMMENDATION) and provenance link; every string is escaped. Sections: header, listing activity, seller (style UNKNOWN banner when nothing is known), why, estimated numbers, value-add plan and sourced model-specific risks, seasonality, transport, system status (timestamps + proving receipt), RECOMMENDATION (action, WAIT, step-up flag), the decision card, the activity trail (agent, what, why, inputs as `/provenance/<id>` links, result, receipt, next action) and the UNKNOWN list.
- `SpineBackend.opportunity_card(item_id)`: works on both backends via Agent 01's API. A card that fails `validate_card` is rendered with a red "failed its own validation" banner, never hidden.
- `server.render_decide / render_hold_notice` were extracted (no behaviour change) so the card page reuses the exact forms: CSRF, frozen payload hash, PIN step-up. Forms carry `return=item`, so a decision, wake or outcome returns to the card. The queue now links to `/item/<id>`; the technical `/areq/<id>` view remains.
- Outcome entry/history appears on the card page too.

## Verification (FACT)
- Reference suite 118 passed; lane D + lane E suite 11 passed (`tools/run_tests.sh`).
- Zero enrichment: all sections render, `validate_card` is empty, and every UNKNOWN path the card lists is on the page.
- Every receipt for the item appears in the trail (R17), with provenance links.
- The decision controls sit after the RECOMMENDATION block. A decision from the card returns to the card, and a refused one returns with `err=`.
- Enrichment via `spine.record_enrichment` appears with basis and provenance, and appears in the trail. Hostile text (`<script>`, `<img onerror>`) in the title, seller and plan is escaped. A card that fails the elementary-advice lint is flagged.
- Same checks on lane D + lane E. Unknown item → 404. A missing operator profile → a clear 503, never a guessed profile.
- Mutation check: unescaping the title makes the hostile-text test fail; file restored.

## Findings for Agent 01
- **Non-editable install:** `card.load_profile()` defaults to a repo-relative `config/operator_profile.v1.json`, and `schemas.contracts_dir()` needs `MBOS_CONTRACTS_DIR` (card.schema.json is not in the package data). Same class as A-10. The UI uses `MBOS_OPERATOR_PROFILE` (the new env var) and `MBOS_CONTRACTS_DIR`.
- R20 acknowledged: a freeze-refused approved request becomes `cancelled_by_freeze` (05's E-12). My pinned test `test_frozen_system_denies_at_the_real_gateway` asserts the current `approved` status and must flip when E-12 lands.

## Hardening follow-up (Agent 01 / 07 acceptance F-26..F-38, mbos @ `d35646d`)
- Re-vendored `card.schema.json` byte-identical (new optional fields: `item.flags`, `status.timeline[].dry_run`, `why_provenance`; `card_version` stays 1.0.0).
- The page shows: a visible **WARNING** for `item.flags` (injection_suspected / needs_review say the listing text needs Michael's eyes); a **"DRY-RUN: simulated, nothing sent"** tag on dry-run timeline entries; lane-supplied reasons link to `why_provenance`. "Waiting for the seller" appears only if the card says `waiting`, which is now false after a dry-run.
- Untrusted display text goes through `mbos.card.clean_text` (control, ANSI, bidi stripped, capped) and is then escaped: titles on the card, queue, holds, outcomes, digest and `<title>`, note statements, and the summary. Data that is edited and re-submitted (the MODIFY payload) is NOT altered.
- Tests: 123 reference + 18 lane D pass. Mutation check: removing the flags banner fails its test.
- **Finding for Agent 01 (hygiene):** the coordinator repo commits `build/` (setuptools output) and `setup.py`. `git archive` includes a stale `build/lib`, and `pip install` from that tree then installs the stale copy (my install lacked `clean_text` until I deleted `build/`). Suggest removing `build/` from git and adding it to `.gitignore`.
