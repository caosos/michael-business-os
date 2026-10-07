# Agent 06: Communications dry-run spec as data (task F-03)

**Date:** 2026-10-07 · **Package:** `comms_spec/` (stdlib only) · **Status of every value:** PROPOSED

**Nothing in this package sends.** It has no network imports, and a test enforces that. Live outbound stays disabled until MICHAEL_DECISIONS #4.

This document closes the open spec items from integration doc §10, row 06: (1) seller Q&A and service intake, (3) the template registry, (4) numeric rate and consent rules, and (6) the E1–E7 thresholds.

| Item | Data file | Used by (pure function) |
|---|---|---|
| (3) Template registry | `data/templates.v1.json`: 12 templates (email/sms/voice). Each has a version, `content_hash` (ADR-0010 MBOS-CJSON-1), `binding` and `commercial` flags, and `approval.status=draft` | `render()` makes a draft payload. It refuses a hash mismatch (edited without a rehash) and missing variables, and it inserts the disclosure itself. `action_constraints()` makes binding ⇒ tier 0 + irreversible + step-up, with category `offer`. |
| (1) Q&A | `data/qa_sets.v1.json`: every flip category (10) and service category (9) in `item.schema.json`, plus common sets. Each question names the economics input it decides | `questions(lane, category)` |
| (4) Rules | `data/comms_policy.v1.json`: send window, rate limits, consent per channel, DNC, opt-out, escalation triggers | `window_check()`, `rate_check()`, `is_opt_out()`, `dnc_check()` |
| (6) Thresholds | `data/acceptance_thresholds.v1.json` (E1–E7) | `audit(receipts, stop_events)` |

## Key numbers and their basis
- **Send window:** the effective window is **08:00–20:00 in the recipient's local time**, with no outbound on Sundays. An unknown timezone means deny.
  - FACT: the legal floor is TCPA, 8am–9pm (47 CFR 64.1200(c)(1)).
  - The 20:00 end is ADR-0005's quiet hours. It also sits inside Florida's 8am–8pm window (FACT).
  - Arkansas-specific rules are UNKNOWN.
  - A reply within 60 minutes of the counterparty's own SMS or email is exempt. **Voice is never exempt.**
- **Rate (RECOMMENDATION, conservative):**
  - SMS and email: 1 message per contact per day while cold, up to 10 in an active thread, and at most 3 unanswered in 7 days.
  - Voice: 1 attempt per day and 2 per week.
  - Global daily caps: SMS 50, email 100, voice 20.
- **DNC:** scrub at most 31 days old (FACT: 16 CFR 310.4(b)(3)(iv); 47 CFR 64.1200(c)(2)). A missing scrub fails closed. Internal suppression is permanent.
- **Opt-out:** CTIA-style keywords plus the FCC 2024 "revoke" and "opt out" terms. The target is **60 s** (E4). FACT: the legal maximum is 10 business days.
- **Consent:** UNKNOWN whether texting a number published in a listing counts as consent. Counsel is required before live use (MICHAEL_DECISIONS #4). Marketing SMS (review requests) needs prior express **written** consent. Commercial email needs a CAN-SPAM postal address and unsubscribe, and a test enforces both placeholders.
- **E1–E7:**
  - E1: disclosure on 100% of calls **and of first messages in a thread** (tightened from "calls" only).
  - E2: consent and DNC check recorded on 100% of sends. Dry-run `not_evaluated` is reported as DRY_RUN_EXEMPT, never as PASS.
  - E3: 0 sends outside the window.
  - E4: suppression within 60 s, and 0 sends after STOP.
  - E5: voice latency p50 ≤ 0.8 s and p95 ≤ 1.0 s. This is an INFERENCE and is not testable in dry-run.
  - E6: `provider_msg_id` on 100% of executed comms receipts.
  - E7: 0 binding sends without an approval.

## Integration notes
- A future comms effector should write each check's result into `details.kind=comms`: `consent_check`, `dnc_check`, `send_window_check`, `first_message`, `disclosure_present`, `binding` and `template_hash`. `audit()` reads exactly those fields.
- The planner (R9, `ActionPlanner`) can use `questions()` + `render()` to draft the payload, and `action_constraints()` to set tier, reversibility and category.
- Pre-approving a template version is Michael's decision: a standing-rule Approval with step-up (MICHAEL_DECISIONS #5). Until then every template is `draft`, and a test forbids any template claiming approval.

## Planner and effector (F-05, F-06)
- `comms_spec/planner.py` `CommsActionPlanner` (an `ActionPlanner`) drafts **first contact only**, from the registry, with a `comms` block in each proposed action. Listing text is sanitized.
- `comms_spec/effector.py` `CommsDryRunEffector` (an `Effector`) is exactly-once and fail-closed, sends only the frozen draft, and writes its checks to `effector_response.comms`.
- On a spine run, `audit()` grades E1/E3/E6/E7 PASS, E2 DRY_RUN_EXEMPT and E5 not testable. The integration requests to A-13 are in `docs/receipts/2026-10-07-f06-comms-dry-run-effector.md`.

## Consent ledger and DNC store (F-07)
- Schema `mbos_comms` (`comms_spec/sql/0001_comms_ledger.sql`, PROPOSED for lane D) is insert-only. Raw contact values live only in `contacts`; everything else uses `cref_…`.
- `comms_spec/ledger.py` writes each consent, revocation (STOP) or DNC scrub in one transaction with provenance and a chained receipt.
- `ConsentLedger` feeds `CommsDryRunEffector(consent_lookup=…, dnc_lookup=…)`. With it wired, E2 is graded PASS or FAIL, not DRY_RUN_EXEMPT.
