# Receipt: F-20, conversational-intake front door (dry-run draft flow)

- **Date:** 2026-10-07 · **Actor:** Agent 06 (fresh bounded worker) · **Task:** READY_QUEUE `F-20` (A-27 DONE)
- **Effect:** this branch only. In-memory drafts in the local UI process. **Nothing is published, sent, spent or marked verified.**

## Provenance
`mbos.intake` (`new_draft`, `answer`, `missing`, `to_inventory_facts`, `load_spec`) and `config/intake/*.v1.json` from the installed mbos (coordinator A-27). No contract changed.

## What was built
- `operator_ui/intake_view.py`: deterministic (no LLM) `start(text)` picks the spec by keyword, records a quoted price ("at least $400") and defect words ("smokes") as `seller_stated`; `apply_answers` records form answers (`seller_stated`, or UNKNOWN for "I don't know"); `inventory_draft` returns facts with basis unchanged, `status=DRAFT`, `published=false`.
- `/intake` (start form), `POST /intake/start`, `GET /intake/<id>`, `POST /intake/<id>/answer`: shows what is known with basis and only the still-missing questions, safety first then material. CSRF and Host guards as elsewhere; all text escaped.

## Verification (FACT)
`tests/test_intake_f20.py` (3 tests): "sell this mower, smokes, at least $400" yields price and defect answers plus the ordered missing questions (no price/defect question, `safety_features` first); `verified` is refused by intake; unknown field refused; hostile text escaped; CSRF enforced; unknown draft 404. Full counts in AGENT_STATUS.

## Limits (UNKNOWN / not done)
Keyword extraction is shallow (price and defect words only); drafts are not persisted and not validated as a full inventory object (no spine inventory store exists). No CLI entry; the UI is the front door.
