# Receipt: E-16, binding-key check scope (Agent 05; from 06 P-06-16)

- **Date:** 2026-10-07
- **Task:** E-16 (P1)
- **External effects:** none.

## Change
- **Before:** the PDP denied any `comms.*` or `publish.*` payload with a key named `binding` (and the other reserved names) at any depth, even `binding: false`. Drafting lanes hit it by accident.
- **Now (policy `2026.10.07-w1.9`):**
  - `binding_payload_keys` are reserved at the **top level** only.
  - `binding_payload_keys_any_depth` (`offer_amount`, `offer_usd`, `counter_offer`, `bid_amount`) stays reserved at any depth.
- The lists are published in the policy file and in `docs/governance/RESERVED_PAYLOAD_KEYS.md`.
- `spine_adapter.binding_key_violations(gov, capability, payload)` lets a lane pin its planners in its own tests.

## Verification (FACT)
- 36 E-16 tests pass. A nested `binding: false`, nested `offer` text and similar key names are allowed. A top-level `offer` is denied (`BINDING_UNDER_COMMS`), and so is a top-level `binding` with any value. The amount names are denied at any depth, and publish uses the same rule.
- The full suite (458 tests) passes on PG16.
- **X-03:** `git ls-files | grep ^build/` returns nothing in this repo, and `build/` is in `.gitignore`.

## Residual risk
A binding offer hidden under a nested generic name is not caught by names alone. Michael's tier-0 review of every `comms.*` payload is the backstop. See the trade-off paragraph in `RESERVED_PAYLOAD_KEYS.md`.
