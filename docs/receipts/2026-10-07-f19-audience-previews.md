# Receipt: F-19, audience view previews (dry-run drafts)

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-19` (A-25 landed; claimed in `780c3a9`)
- **Effect:** this branch only. Read-only previews plus a "check my wording" form that only LINTS. **Nothing is published**; publishing would be a separate gated ActionRequest.

## Provenance
`inventory.schema.json`, `merchandising.schema.json`, `examples/inventory/*` and `mbos.merchandising` (`inventory_errors`, `lint`) @ `51dbd51`, vendored byte-identical. `campaign` and `valuation` schemas were re-vendored in the same pass (additive).

## What was built
- `operator_ui/merch.py` `render_view(inventory, audience)`: **deterministic templates, no LLM**, for `ordinary_classified`, `flipper`, `mechanic`, `parts_buyer`. It uses only the inventory's own facts, defects and terms: defects are disclosed verbatim (in the disclosure list and the prose), terms are copied, every fact's basis is carried with its provenance, unknowns are said ("Not known: hours"), and "verified" appears only for a fact that is verified. It lints before returning; a view that would not pass is **refused with the lint reasons** (`MerchRefused`), never softened. Unsupported audiences are refused, not improvised.
- `/preview` (`MBOS_INVENTORY_FILE`; no spine inventory store exists yet): the facts and defects, then four views, each labelled **DRY-RUN draft: nothing is published** and "passes lint". An invalid inventory is reported and not previewed.
- "Check my own wording": Michael edits headline, body and call to action and can untick a disclosure; the server builds the view with the inventory's own terms and lints it. A view that drops the smoking defect is **REFUSED** ("defect d1 is not disclosed"); overclaims ("perfect condition", "no problems") and false verification ("inspected and certified") are refused with the lint's reasons.
- Current photos are never mixed with an AI "possible finished look": the module has no image or generation code, and a test checks its imports.

## Verification (FACT)
- `tests/test_merch_f19.py` (9 tests): four audiences are byte-identical across runs and pass the lint on the mower example; verbatim disclosures; provenance carried; a seller claim of "runs like new" with a material defect is refused; the UI refuses a dropped disclosure, overclaims and false verification; hostile text escaped; CSRF and Host guards; missing or invalid inventory reported; no network, image or publish code.
- Mutation check: removing the lint gate in `render_view` fails the overclaim test; restored.
