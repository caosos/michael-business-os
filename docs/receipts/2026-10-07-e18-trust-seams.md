# Receipt: E-18, trust and payment seams (Agent 05)

- **Date:** 2026-10-07
- **Task:** E-18 (P2; ADR-0013 §8)
- **External effects:** none. Design, data and validators only.
- **Capabilities granted:** none.

## Built
- `policy/trust/credentials.v1.json`: a specific credential vocabulary (9 ids), reserved bare words, and generic qualifiers.
- `policy/trust/reputation.v1.json`: event types with required evidence, the 5-step penalty ladder, and the appeal state machine.
- `policy/trust/payment_boundary.v1.json`: a spec-only provider boundary (5 operations), all `granted_to: []`.
- `policy/trust/schemas/`: credential-claim, reputation-event and penalty record schemas.
- `src/mbos_governance/trust.py`: validators and the `PaymentProvider` Protocol. `mbos-gov trust check` runs them.
- Design doc: `docs/integration/05-trust-and-payment-seams.md`.

## Verification (FACT)
- 61 E-18 tests pass, and the full suite (519 tests) passes on PG16.
- The bare word "verified" is rejected as a credential id, as a key at any depth, and as a generic id.
- A penalty without evidence is rejected, and so is a reputation event without evidence of the required kind.
- The ladder enforces graduation, a human decision above notice, bounds and appeal windows. An overturned appeal requires a reversal receipt.
- The checker fails if any `money.payment.*` operation has a grantee, or if any agent in the running policy holds a `money.payment.*` capability.
- No `money.payment.*` capability was added to the policy.

## Not asserted
No legal fact. Which jobs need which licence is the jurisdiction pack (E-19). No payment provider is chosen (UNKNOWN; Michael + legal).
