# Trust and payment seams (E-18, ADR-0013 §8)

- **Owner:** Agent 05
- **Status:** DESIGN + DATA + VALIDATORS. Nothing here grants a capability, calls a provider, applies a penalty to a real user, or asserts a legal fact. Level 1 (the private engine) has no marketplace users, so none of this is applied to anyone yet.
- **Files:**
  - Data: `policy/trust/{credentials,reputation,payment_boundary}.v1.json`
  - Record schemas: `policy/trust/schemas/{credential-claim,reputation-event,penalty}.schema.json`
  - Validators: `src/mbos_governance/trust.py`
  - Check: `mbos-gov trust check`
  - Tests: `tests/test_e18_trust.py`

## 1. Credentials: "verified" is never bare
- A credential id is `<specific>_verified`: `identity_verified`, `payment_verified`, `insurance_verified`, `residential_license_verified`, `general_contractor_license_verified`, `electrical_license_verified`, `plumbing_license_verified`, `hvac_license_verified`, `gas_license_verified`.
- **Rejected by the validator:**
  - the bare word as a credential (`verified`)
  - a key named `verified`, `is_verified`, `fully_verified` and similar, at any depth
  - generic ids (`all_verified`, `fully_verified`, `licensed_verified`, …)
  - an id not in the vocabulary
- **A claim** records one credential for one subject: `status ∈ {verified, not_provided, pending, expired, revoked}`, plus evidence, verifier, `verified_at`, `expires_at` and a jurisdiction (for licences).
  - A `verified` status needs evidence of a kind allowed for *that* credential.
  - An honest `not_provided` needs no evidence.
  - A licence is checked against the regulator or a document, never by a payment provider.
  - Deal Sniffer stores the *result* and its reference, never an identity document.
- This vocabulary asserts **no legal requirement.** Which jobs need which licence is the jurisdiction pack (E-19).

## 2. Reputation events are receipted facts
Types: `completed_purchase|sale|job`, `on_time_completion`, `no_show`, `unpaid_winning_bid`, `cancellation`, `dispute_resolved_against`, `seller_misrepresentation_finding`, `response_time_sample`.
- Each event carries **evidence of a kind its type requires**, a `receipt_id` (it is a ledger fact), provenance, a counterparty and a time.
- **An accusation is not a finding.** `seller_misrepresentation_finding` needs a *resolved dispute* and a corroborating artefact (disclosure diff, photos or an inspection report).
- An event without evidence is invalid. There are no stars: standing is derived from documented behaviour.

## 3. Penalties: graduated, evidenced, appealable
Ladder: `notice` → `score_reduction` → `restriction` → `suspension` → `removal`.
- **Evidence-based:** every penalty cites valid, negative, receipted events *about the same subject*, with enough of them (1, 2, 2, 3 and 3 by step). No evidence means invalid.
- **Graduated:** one step at a time. Skipping is allowed only where the data says so (`seller_misrepresentation_finding` may start at `restriction`). An overturned penalty no longer counts toward the history.
- **Human decision above `notice`:** the penalty needs `decision_approval_id` and a human issuer. A model may only propose.
- **Bounded:** reduction points and durations are capped by the ladder data.
- **Appealable:** every penalty has an appeal window (14 or 30 days). It takes effect only after the deadline, except the narrow emergency exception (a misrepresentation finding with resolved-dispute evidence, up to restriction, with a human decision).
- **Appeal states:** `none → filed → under_review → upheld|overturned`, or `none → expired`.
  - An overturned appeal requires a *reversal receipt*.
  - The reviewer must differ from the issuer.
- All numbers are `basis: REC` priors for Michael to confirm.

## 4. Payment-provider boundary (spec only)
- **Principle:** Deal Sniffer is **not the bank**. A marketplace payment provider holds funds and carries the authorization, capture, refund, payout, KYC/identity and compliance obligations.
- **Provider:** replaceable and **not chosen** (UNKNOWN; a Michael + legal decision). `trust.PaymentProvider` is a `Protocol`: authorize / release_authorization / capture / refund / payout, plus `lookup(idempotency_key)`.
  - Amounts are integer minor units.
  - Every call carries an idempotency key and returns a durable event id.
  - **No implementation exists.**
- **Operations:**

  | Operation | Capability | Reversibility |
  |---|---|---|
  | authorize | `money.payment.authorize` | reversible |
  | release_authorization | `money.payment.release` | reversible |
  | capture | `money.payment.capture` | irreversible |
  | refund | `money.payment.refund` | partially reversible |
  | payout | `money.payment.payout` | irreversible |

  Each is tier 0, needs step-up and an idempotency key, and has `granted_to: []`.
- **`money.payment.*` stays granted to nobody.** The checker fails if any operation lists a grantee, or if any agent in the running policy holds a `money.payment.*` capability. These capability names are not in the policy at all.
- **When the time comes** (a separate Michael decision, a schema change and a migration), every call is an ActionRequest with a step-up YES on the exact payload hash, guard checks G1–G8, receipts, caps in the money bucket, and dry-run until authorized. A crashed irreversible call is reconciled by `lookup`, then settled, and never resent (E-05/R22).

## 5. What this does not do
Assert any legal fact, pick a provider, hold funds, issue penalties to real people, or grant anything.
