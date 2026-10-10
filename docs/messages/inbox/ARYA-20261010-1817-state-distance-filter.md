# Owner-requested selectable states alongside distance

Michael explicitly requested selectable states matching his supplied GSA reference: "I want it ... states I can choose ... I want it to look like this." Reference visually reviewed: Location panel with By State / By Distance tabs, searchable Filter states field, scrollable checkbox list and removable selected-state chips (AR/AL/MO/OK shown).

Current queue was checked: F61 exists after F60; no equivalent state-selection task found. Add one bounded next eligible task to the existing lane06 serial queue AFTER F61. Preserve the active F61 worker. No new parallel worker/coordinator and no duplicate F60/F61.

Scope:
- Implement a compact Location panel using the reviewed interaction pattern: explicit By State and By Distance modes, searchable state list, multi-select checkboxes and removable selected-state chips.
- Keep Conway / Faulkner-Pulaski local defaults and existing radius behavior; owner can explicitly broaden. Do not invent county precision unsupported by existing data.
- State the mode semantics visibly. Selecting states must not silently bypass a still-active radius: switching from distance to state selection must be explicit and show the applied scope; if both are supported together, apply their intersection and label it plainly.
- Unknown or unresolved location must fail a strict active location filter, remain separately labelled only under the existing explicit unknown opt-in, and never count as local.
- Persist selected states and location mode through the existing approved saved-filter behavior, including real save/reopen/restart. Preserve price, category, condition, any-terms, row ordering and existing Save/PIN boundary.
- Use current adapter/cache fields only. No new provider, scraping or cache fetch. Unsupported state data stays unknown, never inferred from unrelated text.

Acceptance: focused unit/rendered-form tests for mode switch, multi-state selection, chip removal, search, invalid/unknown state, strict conjunction with price and any active radius, empty selection and saved roundtrip. Actual desktop and mobile screenshots on a clean committed staging artifact, with URL/viewport/filters/time/cache/store provenance. Preserve the already requested Search Now action in the filter card. Report code, tests and staging evidence separately.

Included allowance only. No live8766 reload: the earlier A56 approval was one-time and is spent. No legal eligibility or auction legality claim; separate research handles that question. ACK, queue adoption and actual worker START are separate outcomes.
