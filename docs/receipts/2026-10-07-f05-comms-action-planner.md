# Receipt: F-05, CommsActionPlanner

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-05` (queued by Agent 01 @ `0d107df`; claimed in `5a6294a`)
- **Intent:** draft first-contact comms from the `comms_spec` template registry behind `mbos.interfaces.ActionPlanner`.
- **Effect:** code and tests on this branch only. No sends, and no network imports (test-enforced across `comms_spec/*.py`).

## What it does
- `comms_spec/planner.py` `CommsActionPlanner.plan(item)` returns one first-contact proposal: `seller_first_inquiry` (flip) or `customer_intake_ack` (service). It is never an offer or a quote, since those are binding and come later as their own tier-0, step-up requests.
- The `comms` block carries `template_id`, `template_version`, `template_hash` (MBOS-CJSON-1), the rendered draft, its variables, the question ids, the recipient (ref, contact method, timezone) and its constraints (send window, rate limit, consent prerequisites, DNC, disclosure, tier, reversibility, step-up).
- Listing text is untrusted. `sanitize()` drops control characters, braces, angle brackets and URLs, and caps the length at 80.
- Channel routing: `relay_email`/`email` → email, `phone` → SMS, and `platform`/`in_app`/`gov_poc` → an email draft marked MANUAL ASSIST. `none` returns `[]`, so the spine keeps the item in RESEARCHING.

## Integration seam (FACT, `0d107df`)
`spine._propose` builds the payload from fixed fields, so any extra key on a proposed action is dropped. **A-13 must merge `payload_extension(pa)` (`{"comms": …}`) into the payload** before hashing, so the payload Michael approves carries the draft.

## Verification (FACT)
- `tests/test_comms_planner.py`: 8 tests. The flip (trailer) and service (drywall) proposals validate against frozen `item.schema.json`. An ActionRequest built like `_propose` plus the extension validates against `action-request.schema.json`, using jsonschema 2020-12.
