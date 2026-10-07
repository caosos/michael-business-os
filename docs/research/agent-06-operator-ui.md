# Agent 06: Operator UI / Approval UX (Round Two, Wave One, build lane F)

**Date:** 2026-10-07 · **Branch:** `research/agent-06-communications` · **Contracts:** frozen v1.0.0 from `research/agent-01-coordinator` @ `acb6f3b` (copied byte-identical into `docs/research/contracts/`)

**This is implementation, not live communications.** Nothing in this branch can send SMS, email or voice, or negotiate with anyone. The only effector is a mock that writes dry-run receipts.

Evidence tags: **FACT** (verified by running the code or reading the contracts), **INFERENCE**, **RECOMMENDATION**, **UNKNOWN**.

---

## 1. What was built

`operator_ui/` is a minimal local web UI written in Python with the standard library only: `http.server` and `sqlite3`, with no JavaScript and no framework. It is about 1,840 lines of code plus 29 tests (about 460 lines).

| Module | Role |
|---|---|
| `contracts.py` | Validates every row against the frozen schemas before commit. It uses `jsonschema` when installed, otherwise a built-in Draft 2020-12 subset. A test proves the subset covers every keyword the frozen schemas use. |
| `store.py` | Local ledger. Same-transaction writes, insert-only triggers, hash-chained receipts, `verify_chain`. **A stand-in for lane D's Postgres** (see §5). |
| `approvals.py` | YES / NO / MODIFY / HOLD semantics, HOLD presets, and `tick()` / `wake()` for durable timers. |
| `gateway.py` | Dry-run stand-in for Agent 05's Action Gateway. It runs the 8 execution-guard checks, then calls the effector. Includes crash `resume()`. |
| `effectors.py` | `DryRunEffector`. It refuses `dry_run=False`, replays by idempotency key and emits a `details.kind=comms` block. |
| `views.py` | Card view-model: the "why" data. It backs both the HTML page and the JSON API. |
| `server.py` | Pages (queue, card, ledger) plus `/api/queue.json` and `/api/areq/<id>.json`. |
| `seed.py` | Three **ILLUSTRATIVE** opportunities built from the contract examples: a trailer flip, a drywall service and a generator flip. |

### Run it
```bash
cd /home/michaelos/business-os-worktrees/agent-06-communications
MBOS_OPERATOR_PIN=<pin> python3 -m operator_ui serve --seed --db /tmp/operator_ui.sqlite3   # http://127.0.0.1:8765/
python3 -m operator_ui tick   --db /tmp/operator_ui.sqlite3    # process HOLD timers / expiry once
python3 -m operator_ui verify --db /tmp/operator_ui.sqlite3    # verify_chain
python3 -I -m unittest discover -s tests -t .                 # 29 tests
```
FACT: on 2026-10-07 the server ran on this host, served the queue and JSON API, and returned 403 for a foreign `Host` header. All 29 tests pass on Python 3.10.12, with `jsonschema` absent, so the built-in validator was used.

---

## 2. What the card shows (so Michael can see WHY the system is asking)

| Requirement | Where on the card | Contract source |
|---|---|---|
| Opportunity card | Queue rows plus a full card per ActionRequest | `Item`, `ActionRequest` |
| Flip vs service | A colored **FLIP** / **SERVICE** badge, plus the category. Economics rows differ by lane. | `Item.type`, `Item.category` |
| Recommendation verdict | "System says YES/MAYBE/PASS". This is deliberately labeled as the *machine* verdict, never Michael's decision (ADR-0004 ruling 3). | `recommendation.verdict` |
| Economics summary | Flip: ask, expected buy, parts and materials, target sell, comp range, hours, hold days. Service: quoted revenue, materials, hours, win probability, deposit. Both lanes: EV net, EV $/hour, max loss, cash tied up. | 03 `economics`, `scorecard.derived` |
| Confidence / risk | Composite, confidence, risk sub-score, max loss, reversibility, tier, untrusted-input taint, source ToS risk, **failed gates** (in red), flags | `scorecard`, `ActionRequest` |
| Provenance / sources | A sources table (URL, ingestion method, first seen, `raw_ref`), research findings with evidence tags, and **every provenance row resolved** to its kind: external source, model output, deterministic tool or human decision | `sources[]`, `research[]`, `Provenance` |
| Proposed action | Summary, capability, category, proposer, target, the **frozen payload** shown verbatim, `payload_hash` and idempotency key | `ActionRequest` |
| Audit | The decision history and the receipt timeline (seq, type, actor, intent, `[dry_run]`, `provider_msg_id`, row hash), plus MODIFY lineage links in both directions | `Approval`, `Receipt` |
| YES / NO / MODIFY / HOLD | Four forms on the card. Each carries the `payload_hash_seen` that was rendered. | `Approval` |

The banner on every page reads: **DRY-RUN · nothing leaves this machine · system RUNNING/FROZEN**.

---

## 3. Approval rules: how each is enforced (all FACT; verified by tests)

| Rule | Enforcement | Test |
|---|---|---|
| **YES = frozen payload only** | The form has no payload field. The decision carries the hash Michael saw; a mismatch raises `StaleView` and writes nothing. The stored payload is re-hashed both at decision time and again in the gateway guard, so tampering after approval is denied (`payload_hash_match`). | `test_yes_executes_frozen_payload_dry_run_only`, `test_stale_hash_refused_and_nothing_written`, `test_tampered_stored_payload_never_executes`, `test_tamper_after_approval_denied_by_guard` |
| YES on irreversible / money / offer / external commitment needs step-up | A PIN from `MBOS_OPERATOR_PIN`, compared in constant time, sets `auth_context.step_up=true`. If no PIN is configured the request is **refused** (fail-closed). | `test_step_up_required_for_irreversible` |
| No double execution | A request can only be decided while pending or held. The guard checks `idempotency_unused`, and the effector replays by key. | `test_double_yes_cannot_execute_twice`, `test_a5_…` |
| **NO = reason + close/archive** | An empty reason is refused. The request becomes `rejected`. The Item becomes `ARCHIVED` (default) or `REJECTED` (checkbox off), but only when no other request on that Item is still open. | `test_no_requires_reason_and_archives`, `test_no_without_archive_marks_rejected` |
| **MODIFY = new ActionRequest** | The original row is never mutated: its payload is untouched and it is closed as `rejected`, with a receipt saying "superseded by …". A new `areq` is created with `derived_from`, a new hash, a new idempotency key, `tier 0` and `pending_approval`. **It needs its own YES.** An unchanged payload is refused. The Approval records `modifications.{diff,new_action_request_id,new_payload_hash}`. | `test_modify_creates_new_request_and_never_mutates`, `test_modify_requires_a_change` |
| **HOLD = durable, never auto-executes** | The HOLD approval row and a `hold_timers` row both live in the DB, so a hold survives restart. `tick()` and `wake()` have **no reference to the gateway**: they can only send a reminder (`APPROVAL_REQUESTED`, still held), re-present the request (back to `pending_approval`, which needs a fresh YES), or expire it. | `test_hold_is_durable_reminds_wakes_and_never_executes`, `test_time_hold_re_presents_and_needs_a_fresh_yes`, `test_escalation_re_presents_not_executes`, `test_hold_until_expiry_expires_never_executes` |
| Expired requests cannot be approved | `tick()` marks them `expired` and archives the Item. YES is refused. | `test_expired_request_cannot_be_approved` |

**HOLD presets** (06 gap item 2):

| Preset | `hold_until` | `wake_on` | Re-notify | Escalate |
|---|---|---|---|---|
| Until tomorrow 8am | next 08:00 America/Chicago | time, new_info, price_change | PT24H | — |
| 24 hours | +24h | time, new_info, price_change | PT24H | — |
| 3 days | +72h | time, new_info, price_change | PT24H | — |
| Until new info / price change | none | new_info, price_change, auction_ending | PT24H | PT72H (re-present) |
| Custom time | the chosen local datetime | time plus that preset's set | PT24H | — |

The request's own `expires_at` always wins over a hold: it expires and nothing executes.

**Core-law acceptance tests covered here:**
- A1: all-or-nothing under an injected fault
- A2: insert-only triggers
- A3: `verify_chain` passes, and detects a tampered row
- A4 / A10: every stored row validates, and every receipt's provenance resolves
- A5: a crash after the send but before the receipt resumes with no duplicate
- A6: the YES/NO/MODIFY/HOLD semantics above
- A7: 100% of effector receipts have `dry_run=true`; live calls raise `LiveEffectorForbidden`
- A9: FROZEN, an unreadable kill-switch state, or `system_mode=live` all deny with a `POLICY_DECIDED` receipt

---

## 4. Security posture (wave one, local only)

- The server binds to **127.0.0.1 only** and refuses non-loopback addresses. It returns 403 for a non-local `Host` header (DNS-rebinding guard).
- A per-process CSRF token is required on every POST.
- CSP is `default-src 'none'`, with no scripts. Every untrusted string is HTML-escaped; there is a test for `<script>` inside a payload.
- `auth_context.method = localhost_csrf_session`. INFERENCE: this is adequate only while the UI is reachable solely from the box itself, for example over `ssh -L 8765:127.0.0.1:8765 michaelos`. **Remote access, WebAuthn/TOTP step-up and session auth are lane E (Agent 05) work.** The PIN is a placeholder, not strong authentication.

---

## 5. Integration seams: what other lanes replace

| Seam here | Replaced by | Notes |
|---|---|---|
| `store.Store` (SQLite) | **Lane D / Agent 04** Postgres DDL + State MCP | Same guarantees and same method names (`tx()`, `put_*`, `add_*`, `verify_chain`). ADR-0001 still holds; SQLite is only the dev and test harness. `row_hash = sha256(canonical_json(row − row_hash) ‖ prev_hash)`, where `canonical_json` = sorted keys, compact separators, UTF-8. **RECOMMENDATION:** 04 adopts the same canonicalization (the frozen examples' hashes are illustrative and match no canonical form — FACT, checked). |
| `gateway.DryRunGateway` | **Lane E / Agent 05** Action Gateway + PDP + budget ledger + PANIC | The 8 checks and their names follow ADR-0005. Real-world spend is deny-all. Tiers above 0 are denied (MICHAEL_DECISIONS #5). |
| `effectors.DryRunEffector` | 06 live effectors (Telnyx/Postmark/Vapi) **after MICHAEL_DECISIONS #4** | The `details.kind=comms` block records `consent_check`, `dnc_check` and `quiet_hours_check` as `not_evaluated`. This is honest: the consent/DNC ledger is not built yet. |
| `ApprovalService.tick()` / `wake()` | A DBOS durable wait plus a scheduled workflow (lane A) | Same semantics. `wake(areq, condition)` is the hook for 02/03 when a price change or new information arrives. |
| `seed.py` | Real Items from lanes B and C | The demo data is labeled ILLUSTRATIVE throughout. |
| Notifications | ntfy (alerts only) / optional Telegram | Not built. Re-notify writes an `APPROVAL_REQUESTED` receipt, which is the trigger point for a later notifier. |

---

## 6. Deviations, gaps and UNKNOWNs

- **Python 3.10, not 3.12+ (ADR-0008).** FACT: the host has Python 3.10.12, no pip and no `jsonschema`. The code is stdlib-only and 3.10-compatible, and will run unchanged on 3.12.
- **MODIFY closes the original as `rejected`.** The frozen status enum has no `superseded` value. Supersession is recorded in the APPROVAL_DECIDED receipt (`after_state`) and in `approval.modifications`. **Needs coordinator review:** add `superseded` in v1.1, or accept this mapping.
- **Expiry is recorded as an `ITEM_STATE_CHANGED` receipt** with `entity_type=action_request`. The receipt type enum has no `ACTION_EXPIRED`. Same request for coordinator review.
- **One item, several requests.** NO, expiry and archive only change the Item state when no other request on that Item is still open. INFERENCE: this is the least surprising behavior; 01 may prefer otherwise.
- **Item state after YES** follows APPROVED → ACTING → ACTED. `OUTCOME_RECORDED` and `LEARNED` belong to lanes D and C.
- **Not built (out of scope for wave one):**
  - Telegram quick-decide
  - ntfy push
  - the PANIC button (05 owns PANIC; the UI only displays the system state)
  - multi-user approvers (UNKNOWN; a Michael decision)
  - `scope=session|standing_rule` (delegation is disabled per MICHAEL_DECISIONS #5)
- **Still owed from my round-two gap list** (integration doc §10, row 06):
  - (1) generalized seller Q&A sets and service intake
  - (3) template registry
  - (4) numeric rate and consent rules
  - (6) thresholds for E1–E7

  These are research/spec items for the comms lane, which stays dry-run. This document covers gap (2), approval UX, and gap (5), `idempotency_key` and hashes on sends.
- **(7) Ownership of 07's sends: confirmed.** 06's effector layer is the only send path, and 07 produces ActionRequests that appear in this same queue.
