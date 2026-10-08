"""QA orchestration CLI.

  python -m mbos_qa contracts [--drift-ref REF]   contract validation runner only
  python -m mbos_qa e2e                            run flip + service fixtures, write reports + packets
  python -m mbos_qa interop                        cross-lane checks against peers' actual code
  python -m mbos_qa builds --workdir DIR            run every lane's own suite from a clean archive
  python -m mbos_qa spine                          A1–A10 spec suite against Agent 01's REAL spine (G-02)
  python -m mbos_qa install-pins                   (re)install mbos + mbos_governance from the pins and verify byte identity
  python -m mbos_qa card                           G-05: Deal Sniffer card acceptance (pure + reference + RC) → CARD_ACCEPTANCE.md
  python -m mbos_qa run [--drift-ref REF]          everything; writes docs/qa/ACCEPTANCE_REPORT.md
  python -m mbos_qa pin --ref COMMIT               re-pin contracts after an Agent 01 semver bump

Exit status is non-zero if any contract check or acceptance test fails.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict

from . import report
from .contracts import CONTRACTS_DIR, run_contract_checks, run_gap_probes
from .e2e import run_all
from .harness import build

QA_ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = QA_ROOT.parent
OUT = REPO / "docs" / "qa"

GROUPS = OrderedDict([
    ("test_a01", "A1 atomic state + receipt (both or neither)"),
    ("test_a02", "A2 immutability (insert-only triggers)"),
    ("test_a03", "A3 hash-chain verification + tamper"),
    ("test_a04", "A4 provenance resolution"),
    ("test_a05", "A5 crash / restart / idempotency"),
    ("test_a06", "A6 YES / NO / MODIFY / HOLD semantics"),
    ("test_a07", "A7 100% dry-run audit"),
    ("test_a08", "A8 LLM spend cap enforcement"),
    ("test_a09", "A9 PANIC fail-closed"),
    ("test_a10", "A10 contract conformance"),
    ("test_g_", "G marketing (G1, G2, G4 + injection)"),
])

FINDINGS = [
    ("F-1", "FACT", "01/04", "Hashes in `contracts/examples/` (`payload_hash`, `row_hash`) do not reproduce under any "
     "tried canonical form. The contract never pins the exact bytes. See F-13/F-14 for the effect on the real lanes.",
     "RECOMMENDATION: Agent 01 pins one canonical form in the contract text and regenerates the example hashes."),
    ("F-2", "FACT", "01", "5 rules stated in ADR/integration prose are NOT enforced by the frozen schemas (see "
     "'Contract gap probes'). The QA runtime enforces each one.",
     "RECOMMENDATION: tighten in v1.1.0: MODIFY `modifications.required=[new_action_request_id,new_payload_hash]`; "
     "HOLD `hold.required=[hold_until,wake_on]`; `prev_hash` pattern; dry_run const for MVP via policy, not schema."),
    ("F-3", "FACT", "01/05", "ActionRequest `status` has no `superseded` value, so a request closed by MODIFY must "
     "reuse `rejected` (QA records `after_state.superseded_by`).",
     "RECOMMENDATION: add `superseded` (minor bump) so NO-rejections and MODIFY-closures are distinguishable in LEARN."),
    ("F-4", "FACT", "04", "SQLite `INSERT OR REPLACE` silently bypassed the append-only DELETE trigger until "
     "`recursive_triggers=ON` (caught by A2, fixed in the mock). Postgres analogue: `TRUNCATE` does not fire "
     "row-level DELETE triggers.",
     "RECOMMENDATION: Agent 04 adds a `BEFORE TRUNCATE` statement trigger and `REVOKE TRUNCATE`; A2 must test it."),
    ("F-5", "FACT", "04", "A hash chain alone cannot detect deletion of the newest rows (strict xfail "
     "`test_tail_truncation_detected` against the QA mock). From reading the code, Agent 04's lane already has "
     "external head anchors (`state/mbos_state/chain.py` write_anchor / verify_lines). QA has not exercised them yet.",
     "RECOMMENDATION: keep the 04 anchors. Wire them into A3 when the suite runs on lane D."),
    ("F-6", "FACT", "05/04", "Budget reservations must be durable. The mock ledger is in memory and lost its "
     "reservation on a hard kill (caught by A5). Recovery now re-reserves under the cap.",
     "RECOMMENDATION: write `budget_ledger` rows in the same transaction as `ACTION_EXECUTING`."),
    ("F-7", "INFERENCE", "05", "A8 and A9 are proven only against in-process mocks. No LiteLLM proxy, OpenBao "
     "lease or egress proxy exists yet.",
     "RECOMMENDATION: re-run A8 and A9 (plus B29) through `MBOS_QA_IMPL` once lane E ships. Do not sign off the MVP on mocks."),
    ("F-8", "INFERENCE", "04", "A2 cannot prove the `agent_write` *role* is denied, because SQLite has no roles.",
     "RECOMMENDATION: the Postgres A2 run must connect as `agent_write` and as `gateway`."),
    ("F-9", "FACT", "01", "Item-level state with several ActionRequests has no specified rule. QA rule: any pending → "
     "AWAITING_APPROVAL; else any approved → APPROVED; else any held → HELD; all rejected → REJECTED → ARCHIVED. "
     "QA also assumes these edges: HELD → AWAITING_APPROVAL on wake, MAYBE → RESEARCHING.",
     "RECOMMENDATION: Agent 01 confirms or replaces this rule in the state-machine spec."),
    ("F-10", "FACT", "01/05", "The receipt vocabulary has no event for 'in-flight at freeze' or for guard denials. "
     "QA uses `POLICY_DECIDED` with `after_state.guard=deny`.",
     "RECOMMENDATION: add `ACTION_DENIED` and `ACTION_INFLIGHT_AT_FREEZE` (minor bump) or bless the QA convention."),
    ("F-11", "INFERENCE", "06/Michael", "approval.schema says step-up is required for *irreversible* actions. Every "
     "seller or customer email is irreversible, so every email approval needs WebAuthn/TOTP. That risks approval "
     "fatigue.",
     "RECOMMENDATION: Agent 06 UX considers a session-scoped step-up. This is an owner decision only if it would "
     "relax the rule."),
    ("F-12", "FACT", "01", "Agent 01's `validate_contracts.py` does not check `format` (date-time). The QA runner does.",
     "RECOMMENDATION: adopt `FORMAT_CHECKER` in the coordinator validator."),
    ("F-13", "FACT", "01/04", "RULED by ADR-0010 (MBOS-RH-1; Agent 04 sole ledger owner). Conformance evidence is in "
     "[INTEROP_REPORT](INTEROP_REPORT.md): lanes 05 and 07 and the reference/01 SQL twins verify the vectors "
     "receipt_chain. Still OPEN: 04's ledger hashes `jsonb::text` (D-02, CLAIMED) and `mbos.receipts` is defined "
     "twice (A-01 phase 2).",
     "RECOMMENDATION: close when the interop rows '04 SQL twin' and '5 ledger' turn PASS. G-02 re-runs this."),
    ("F-14", "FACT", "03", "RULED by ADR-0010 (MBOS-CJSON-1). Lanes 01, 02, 05 and 07 and both SQL twins pass 10/10 "
     "vectors and 6/6 rejections. Lane 06 no longer hashes on its own (it goes through 01's spine). Lane 03 passes "
     "9/10 and 2/6: it fails 'number edge cases' and accepts integers above 2^53−1, `1e21`, non-BMP member names "
     "and U+0000.",
     "RECOMMENDATION: C-02 (READY) closes it. Re-run `python -m mbos_qa interop`."),
    ("F-15", "FACT", "03", "Agent 03 changed `opportunity`, `scorecard` and `service-job` schemas without changing "
     "their `$id`, contrary to the ADR-0004 mitigation. Its 13 scored examples (26 documents) still validate "
     "against frozen v1.0.0, so nothing breaks today.",
     "RECOMMENDATION: 03 bumps the `$id` / version on its next schema change. 01 re-pins through a semver bump."),
    ("F-18", "FACT", "01", "FIXED at a910ad9 (verified on the real spine): NO without a reason raises "
     "`DecisionRefused` and leaves no partial write. It used to surface as `ContractViolation`.",
     "None. Kept for the record."),
    ("F-19", "FACT", "01", "FIXED by A-13 (aa88e7a), verified on the real spine at a910ad9: the planner's `draft` is "
     "frozen verbatim into the approved payload (`payload.draft`) and covered by `payload_hash`. Michael approves "
     "the text that goes out.", "None. Kept for the record."),
    ("F-20", "FACT", "01", "FIXED at a910ad9 (verified): `spine.record_outcome(..., attribution=...)` stores "
     "lead attribution.", "None. Kept for the record."),
    ("F-21", "FACT", "01", "FIXED at ca6d056 (P-07-8), verified on the real spine: a proposed action's `draft` gets "
     "its own provenance record, cited in the request's `provenance_ids`, that resolves to its template, prompt hash "
     "and model.", "None. Kept for the record."),
    ("F-22", "FACT", "05", "FIXED by 05's E-13 (verified on the RC stack at e6afc28): `publish.listing.create` is now granted "
     "propose-only; publishing needs Michael's step-up and then executes once in dry-run (G1/G4 publish cases green). "
     "Original: the policy granted it to nobody, so the flip/publishing path was denied.", "None. Kept for the record."),
    ("F-23", "FACT", "01", "FIXED by 01's R21 (verified at f8407c9, lane D+E): a PDP-denied proposal leaves the item RECOMMENDED "
     "with no pending request instead of AWAITING_APPROVAL (regression test: an ungranted capability).", "None. Kept for the record."),
    ("F-24", "FACT", "05 + 01", "FIXED by 05's E-13 (verified on the RC stack at e6afc28): a request refused with a "
     "G7:PANIC_* reason (L1/L2/L3, empty, corrupt or unavailable PANIC state) now goes approved → cancelled_by_freeze in the "
     "same transaction as ACTION_FAILED. All 8 spec A9 cases pass, including the replay regression "
     "(`test_a_request_denied_by_a_freeze_cannot_fire_once_the_switch_is_readable_again`). Original: the stale approval "
     "executed after the freeze lifted.", "None. Kept for the record."),
    ("F-25", "FACT", "05 + 01", "RULED (R22) and FIXED by 05's E-13 (verified at e6afc28): the dry-run provider ledger is the durable "
     "`mbos.effector_calls`. A crash AFTER the send settles `executed`/ACTED with no second call; a crash BEFORE the send "
     "settles failed + RECONCILED with zero calls. The spec A5 now asserts R22, including that the settlement is truthful "
     "(a send that happened is never recorded as failed).", "None. Kept for the record."),
    ("F-26", "FACT", "01 (card) **high**", "`build_card` raises on malformed lane enrichment (non-dict enrichment or block, non-iterable "
     "`recent_activity`/`why`, non-numeric `peak_months`, non-dict risk entries, string money in the reasons text, ...): "
     "250 of 300 seeded fuzz inputs crash it (`card.py` lines 86, 308, 335, 344, 356, 363, 370). ADR-0011 rule 2 says malformed "
     "enrichment 'degrades to UNKNOWN'. Through the real path one lane writing `seller` = `[1,2,3]` via `record_enrichment` "
     "makes the whole opportunity unviewable (both backends).",
     "RECOMMENDATION: type-check every block and entry in the builder (a block that is not a dict is UNKNOWN; skip entries "
     "that are not well-formed) and keep a fuzz test (this one) in 01's suite. `record_enrichment` could also reject "
     "non-dict data."),
    ("F-27", "FACT", "01 (card)", "`build_card` copies malformed datum parts through, so it RETURNS a card that fails its own "
     "contract: `provenance_id` not matching the pattern, non-string `unit`/`note`, non-numeric `low`/`high`, `value: null`, "
     "`peak_months` outside 1–12, risk `risk`/`source` that are not strings. `validate_card` catches them; the builder should "
     "not emit them.",
     "RECOMMENDATION: sanitise per field (drop the bad field, or the whole datum to UNKNOWN) so build_card output always validates."),
    ("F-28", "FACT", "01 (card) + 02/03", "Lane values are shape-checked, not value-checked: `posted_at` = 'not a date', a date in "
     "2999, `age_days` = -40, `stale_risk` = 'banana', a resale range with low > high and a negative opening offer are all "
     "shown as FACT on the card. ADR-0011 says dates are never fabricated.",
     "RECOMMENDATION: validate dates (ISO, not in the future), enums (`stale_risk`, `demand_now`), ordering of ranges and "
     "non-negative money; otherwise UNKNOWN with the reason."),
    ("F-29", "FACT", "01 (card) + 03", "Lane C's `why` lines are bare strings with no basis or provenance, rendered verbatim "
     "under 'WHY IT'S INTERESTING'. A lane (or a compromised one) can print 'Michael already approved this purchase' or "
     "'Seller is a verified dealer' as if it were a finding. This breaks ADR-0011 rule 2 (every datum has a basis).",
     "RECOMMENDATION: make `why` entries datums ({text, basis, provenance_id}) and show the basis; drop entries without."),
    ("F-30", "FACT", "01 (card) + 03 (**R18 not enforced**)", "The elementary-advice lint is a short regex list. Of 42 phrasings an "
     "experienced mechanic would reject, 19 pass `validate_card` (e.g. 'Test compression', 'See if it starts', 'Check the "
     "fluids', 'Check tire pressure'), and trivial whitespace evasion works ('Check  compression', a newline, NBSP, a "
     "hyphen). A 'source' is any non-empty string ('n/a', 'trust me', '-') and launders elementary advice. There is no "
     "model-specific marker in the contract (`kind` has no such value), though the ADR says lanes 'mark' content; FACT risks "
     "without any source are accepted; `why` is not linted.",
     "RECOMMENDATION: normalise whitespace/punctuation before matching; widen the list from the profile (data, not code); "
     "require a real source (URL, manual section, part number) or provenance_id; add a `model_specific` flag; lint `why`."),
    ("F-31", "FACT", "01 (card) **high, honesty**", "After a DRY-RUN execution the card's timeline shows 'CONTACT SENT' and the "
     "recommendation says 'Already contacted; waiting on the seller's reply' / 'CONTACT / WAIT FOR RESPONSE'. Nothing was "
     "sent (dry-run). Michael would wait for a reply from a seller no one contacted. Both backends.",
     "RECOMMENDATION: map a dry-run ACTION_EXECUTED to a distinct stage ('CONTACT DRY-RUN'), never set `waiting`, and say "
     "'nothing was sent' on the card while the system is dry-run."),
    ("F-32", "FACT", "01 (card + spine)", "Timeline events are mapped from fields receipts do not carry: `OUTCOME_RECORDED` receipts "
     "have no `after_state.kind`, so EVERY outcome becomes CLOSED (a lead-attribution record at intake closes a live "
     "lead on the timeline; a recorded seller reply is also CLOSED, never SELLER RESPONDED), and `APPROVAL_DECIDED` carries no "
     "`after_state.decision`, so Michael's YES never produces CONTACT APPROVED although the ledger has it. "
     "NEGOTIATING/QUALIFIED are correctly never invented (200 adversarial histories + 9 real flows).",
     "RECOMMENDATION: derive stages from the typed documents (join the outcome and approval rows by id) or add `kind`/"
     "`decision` to the receipts' `after_state`; also stop `record_outcome` moving the item to OUTCOME_RECORDED for a "
     "non-closing kind such as `message_replied`/`lead_attributed`."),
    ("F-33", "FACT", "01 (card)", "`card_hash` depends on the ORDER of the action-request list: the 'live' request is taken as the last "
     "element, not the latest by `created_at`. 19 of 60 shuffles of the same rows change the hash and the recommendation's "
     "`action_request_id`.",
     "RECOMMENDATION: sort requests by (created_at, id) in the builder; keep the 60-shuffle test."),
    ("F-34", "FACT", "01 (card)", "`validate_card` does not recompute `card_hash`: a card whose recommendation was changed to BUY "
     "with the old hash validates.",
     "RECOMMENDATION: recompute sha256_of(body) in validate_card and reject a mismatch."),
    ("F-35", "FACT", "01 (card) + 06 **high**", "Untrusted listing text reaches `render_text` unescaped. A title/city/state/url/source or receipt intent "
     "containing a newline forges a section ('\nRECOMMENDATION: BUY\n  Michael already approved.' shows two "
     "RECOMMENDATION lines and adds lines to the card); ESC sequences (clear screen, OSC-8 hyperlinks), CR, BEL and BS reach the "
     "terminal; a 1 MB title gives a 1 MB view. The contract is unaffected, so only the text view is exposed; the JSON is "
     "structurally fine. Same through the real pipeline.",
     "RECOMMENDATION: in render_text, replace control characters and line breaks inside untrusted fields with a visible "
     "marker, and truncate each field (for example 120 chars) with an ellipsis."),
    ("F-36", "FACT", "01 + 02 **high, poison pill**", "A listing containing a NUL (legal JSON a seller can send, illegal in MBOS-CJSON-1) "
     "raises `CanonicalError` in `build_card` and, worse, aborts the whole `discover` workflow batch: DBOS cannot pickle the "
     "exception (`PicklingError`) so the root cause is hidden and later good listings are not ingested. Both backends.",
     "RECOMMENDATION: quarantine the one bad record at normalize/ingest (receipt + skip), and make domain exceptions "
     "picklable (or convert to a plain error at the step boundary)."),
    ("F-37", "FACT", "01 (card)", "An Item flagged `injection_suspected` shows nothing about it on the card; Michael should be told the "
     "listing text looked like an attack.",
     "RECOMMENDATION: add a one-line warning to `why`/the text view when the flag is present."),
    ("F-38", "FACT", "01 (card)", "`build_card` does not filter its receipt list: if a caller passes another item's receipts they "
     "appear in this item's trail. The loaders are correct, so this is defensive only.",
     "RECOMMENDATION: ignore receipts whose item_id is another item (keep request-scoped ones)."),
    ("F-39", "FACT", "01 (ADR-0011 vs ADR-0004)", "The card recommendation vocabulary includes HOLD, which is also Michael's HOLD decision. "
     "ADR-0004 rule 3 says the two vocabularies are never conflated; 'RECOMMENDATION: HOLD' can be read as the system having "
     "parked the item.",
     "RECOMMENDATION: rename the card's HOLD (e.g. 'GATHER' or 'WAIT') or label it 'research hold'."),
    ("F-40", "FACT", "01 + 05", "Release candidate: the spine's `decide` requires step-up only for irreversible/money-like requests, "
     "but lane E's policy stamps `step_up=required` on publishing (`GATED:publishing:tier0`). A YES without step-up is "
     "ACCEPTED (APPROVAL_DECIDED), then the gateway refuses it (`STEP_UP_REQUIRED`, `AUTH_CONTEXT_REQUIRED`), the item ends "
     "FAILED and the request is left `approved`: Michael's approval is silently lost. With step-up it executes once.",
     "RECOMMENDATION: have `decide` consult the PDP decision recorded on the request (or the policy) and refuse a YES "
     "that lacks the step-up the policy requires, with a clear message; settle a guard-refused request as failed, not `approved`."),
    ("F-41", "FACT", "05 (least privilege)", "Release candidate: after E-13 the spine's single proposer identity `agent-01-coordinator` holds propose-only grants "
     "for EVERY gated money-moving capability (`money.payment.send`, `purchase.create`, `offer.*`, `price.change`, "
     "`commit.external`) as well as comms and publishing; only `comms.voice.call`, `comms.message.send` and "
     "`schedule.appointment.create` are ungranted. A proposal still needs Michael's YES with step-up (verified: "
     "`GATED:money:tier0; step_up=required`), so this is not an authority break, but all drafting lanes share this one "
     "identity, so a buggy or hostile planner can put a payment request in front of Michael.",
     "RECOMMENDATION: grant per capability to the lanes that actually draft it (06 comms, 07 publishing), keep the spine "
     "identity to what its default planner emits, and add offer/purchase grants only when their planners exist."),
    ("F-42", "FACT", "01 (A-15)", "G-08: `workflows.propose_followup` commits the request (item AWAITING_APPROVAL, request pending_approval) in one "
     "transaction and only THEN enqueues the `followup:<id>` gate on the `followups` queue. If the process dies (or the enqueue raises) between the two, "
     "the request is orphaned: no gate workflow exists, a retry is refused (item is no longer ACTED), and Michael's YES is ACCEPTED "
     "(`approved`) but nothing executes and nothing recovers it. Same silent-loss shape as F-40.",
     "RECOMMENDATION: start the gate inside the creating transaction's outbox, or have startup/reconcile scan `pending_approval` requests with no "
     "`followup:<id>` workflow and start the missing gates (idempotent: the workflow id is deterministic)."),
    ("F-43", "FACT", "01 + 05", "G-08: a follow-up for a capability nobody may propose (e.g. `comms.voice.call`) returns "
     "`{action_request_id: None, policy_denied: True}` and leaves NO request and NO receipt, so the card and the ledger cannot explain why "
     "nothing happened (a negative cost, by contrast, is recorded as a rejected request with POLICY_DECIDED receipts). R17: no invisible outcomes.",
     "RECOMMENDATION: record every denied proposal as a rejected ActionRequest with its POLICY_DECIDED receipt, as the negative-cost path already does."),
    ("F-44", "FACT", "01", "G-08: `propose_followup` does not validate its `proposed_action`. `{}`, `None`, a list, or a dict missing "
     "capability/summary/reversibility escape as a raw KeyError/AttributeError instead of DecisionRefused. Nothing is written (atomic), "
     "so this is robustness, not safety, but the caller (and the Telegram handler) gets a stack trace.",
     "RECOMMENDATION: validate the shape first and raise DecisionRefused with a message naming the missing field."),
    ("F-45", "FACT", "01 (A-15) + 04", "G-08: eight concurrent `propose_followup` calls on one ACTED item create TWO live requests (reproduced "
     "3/3 on lane D + E; the reference spine is not affected). Michael's YES on both is accepted: one executes, the other is left `approved` "
     "with no execution (silent loss, as F-40). The duplicate effect is avoided only because the second gate finds the item already ACTED.",
     "RECOMMENDATION: take a row lock on the item (SELECT … FOR UPDATE) or use a conditional ACTED → AWAITING_APPROVAL transition inside the "
     "transaction so the loser gets DecisionRefused; add a partial unique index on live requests per (item, follow-up) in lane D."),
    ("F-46", "FACT", "01 (release gate)", "G-08: the gate cannot go red on a WEAKENED frozen contract. Dropping `scope` from "
     "approval.schema.json `required` (examples still validate) left all six checks PASS; `validate_contracts.py` checks only that the examples "
     "validate, and nothing pins the contract bytes.",
     "RECOMMENDATION: add a CONTRACTS.sha256 manifest (or compare against the frozen v1.0.0 tag) and fail on any byte difference without an ADR-bump."),
    ("F-47", "FACT", "01 (release gate)", "G-08: the gate cannot go red on a test suite that tests nothing. With every test marked skip, "
     "`pytest -q` reports `234 skipped` and exits 0, so the check is PASS. Deleting a failing test also goes green (no test-count floor).",
     "RECOMMENDATION: parse the pytest summary and require passed >= a pinned floor and skipped <= a pinned ceiling (today 233 / 1)."),
    ("F-48", "FACT", "01 (release gate)", "G-08: `pins_check` compares only `.py` files that exist in the pushed head. Verified PASS with (a) an extra stale `.py` "
     "left in the installed package, (b) a replaced `schemas/*.json` in the installed package. It also compares against the LOCAL `origin/*` ref, so "
     "without `--fetch` a stale clone is checked against stale heads. (Modified, deleted and uninstalled `.py` all turn it red.)",
     "RECOMMENDATION: compare the full file set both ways (extra files and .json included) and fetch by default, or print the age of each ref."),
    ("F-49", "FACT", "01 (release gate)", "G-08: in the gate's own lane D/E run `effector 0 (live 0)`: no action executes, so its live-effector and "
     "dry-run assertions are vacuous there. A live-mode policy (`system_mode: live`) was caught only because the pytest check and the runner failed "
     "on it, i.e. the protection lives in the test suite (see F-47), not in the gate.",
     "RECOMMENDATION: have the gate's e2e approve one fixture action and assert exactly one dry-run effector row and zero live rows."),
    ("F-50", "FACT", "01 (release gate)", "G-09: the new default `git fetch -q origin` in `tools/release_gate.py` ignores its own exit code. With an unreachable "
     "origin (rc 128) the gate carries on against the stale local `origin/*` refs and prints PASS, i.e. the F-48 'compare against the real heads' guarantee is silently off. "
     "Also, the stale-install check only looks at `.py`/`.json` files, so an extra `.txt`, `.sql`, `.so` or `.pth` file in an installed lane package is not drift. And "
     "`test_action_path_check_requires_real_executions` greps the gate's source text instead of running the check.",
     "RECOMMENDATION: make a failed fetch a FAIL (or print a loud 'STALE REFS' line and exit non-zero unless `--no-fetch`); compare every file in the package dir; "
     "replace the source-grep test with one that feeds the check a RESULT with 0 effector calls."),
    ("F-51", "FACT", "01 (card)", "G-10: `economics.current_cash_context` takes ANY value in the profile as Michael's FACT: a negative number, a boolean, a list, a dict, "
     "and NaN (which crashes `build_card` with CanonicalError). Repro: set `current_cash_context.value` to -50 / true / [] / NaN in a profile and build a card.",
     "RECOMMENDATION: accept only a finite number >= 0 (or a documented level string); anything else is UNKNOWN."),
    ("F-52", "FACT", "01 (card) + 03", "G-10: NaN, infinity, 1e308 and numeric strings in the scorecard (`cash_tied_up`, `time_to_cash_days`, `ev_net_profit`) crash `build_card` "
     "(CanonicalError / ValueError in `_fact_reasons`). The new fields guard with `_finite`, but older fields (`total_cash_at_risk`, `expected_net_profit`) copy the value unchecked. "
     "Same class as F-26: a card must never crash.",
     "RECOMMENDATION: run every scorecard number through `_finite` before it becomes a datum."),
    ("F-53", "FACT", "01 (card)", "G-10: a negative cash at risk (-100) gives cash_multiple 0.5 and velocity -0.25 for a +$50 deal; negative or zero days and zero cash still give class MICRO_FLIP; "
     "a cash of 1e-9 gives a multiple of 5e10. Nothing in `_velocity_fields`/`_class_of` requires cash > 0 and days > 0.",
     "RECOMMENDATION: cash <= 0 or days <= 0 (or an implausible multiple) makes multiple, velocity and class UNKNOWN."),
    ("F-54", "FACT", "01 (card)", "G-10: the class thresholds are DATA but unvalidated. String thresholds crash `_class_of` (TypeError); NaN / None / negative thresholds silently shift a deal to "
     "QUICK_TURN; a missing capital_intensive block removes the class; with all three blocks missing every deal is STANDARD_FLIP (not UNKNOWN).",
     "RECOMMENDATION: validate the three blocks (finite numbers, ordered); an invalid block makes the class UNKNOWN with a reason."),
    ("F-55", "FACT", "01 (card)", "G-10: `liquidity` shows '150% sale probability', '-20%' and '-3 days on market' as INFERENCE (the neighbouring p_ok/salvage fields are range-checked).",
     "RECOMMENDATION: require 0 <= sale_prob <= 1 and days > 0, else UNKNOWN."),
    ("F-56", "FACT", "01 (card)", "G-10: the gross-profit low/high is not checked: reversed comps give low 640 > high 40; a deterministic value of 5000 is shown beside a range of 40..640; "
     "a negative cost_out shifts the range to 2300..2900.",
     "RECOMMENDATION: show low/high only when low <= value <= high and cost_out >= 0 (same rule as the resale range, F-28)."),
    ("F-57", "INFER", "03 + 01", "G-10: two sources of 'the cash situation'. The card reads only Michael's profile (UNKNOWN); lane C reads `economics.context.current_cash` from the item "
     "(`known: true`, e.g. 1200 in the mower case) and applies a cash-pressure factor to the rank. Any lane can write that item field, so the engine may be using a cash figure Michael never stated.",
     "RECOMMENDATION: one source (the operator profile, passed to the engine); the item field is ignored or rejected."),
    ("F-58", "FACT", "03", "G-10: the late-season mower with tight funds is 'wrong buy today' only as a rank_score of 0.14 (vs 1.06 in season). The reasons never say so in words "
     "('season', 'cash pressure', 'funds'); the only mention is the formula text. The decision is PASS either way.",
     "RECOMMENDATION: add a reason line with the applied seasonality and cash-pressure factors and the sentence the owner used."),
    ("F-59", "FACT", "01 (merchandising)", "G-11: the lint's prose checks are three short regexes, so a view that minimises or denies a MATERIAL defect passes: 'Runs when it wants to. Sold as is, minor cosmetic smoke.', "
     "'Small amount of exhaust haze, normal for the age', 'Strong runner, just needs a tune-up', 'zero complaints', 'Runs excellent', 'Runs like a top', 'Does not smoke at idle', "
     "'Pre-purchase inspection passed' (13 phrasings). The patterns also use literal single ASCII spaces: 'like\u00a0new', 'Like  new', 'L1KE NEW', Cyrillic i, zero-width characters and 'NOTHING   WRONG' all pass (7).",
     "RECOMMENDATION: (1) normalise before matching (NFKC, strip zero-width, collapse whitespace, confusables skeleton); (2) for a material defect REQUIRE its verbatim text in the headline or the first 300 characters of the body, and forbid softeners ('minor', 'cosmetic', 'normal for', 'just needs') near it; a regex deny-list can never be complete."),
    ("F-60", "FACT", "01 (merchandising)", "G-11: a material defect does not have to be visible in the prose at all (a 3900-character body of fluff with the defect only in the disclosures list passes), and the `label` enum is not linted: "
     "label 'Ready to Work' or 'Quick Turn' on a mower that smokes under load passes.",
     "RECOMMENDATION: the prose-visibility rule from F-59, and a label-vs-defect table (a material defect forbids 'Ready to Work')."),
    ("F-61", "FACT", "01 (merchandising)", "G-11: the lint trusts the inventory. Setting a defect's `severity` to `minor` in the inventory switches off all prose checks ('Runs great and mows fine.' then passes); deleting the defect from the inventory "
     "makes a view without it lint clean. There is no provenance on severity and no append-only defect register.",
     "RECOMMENDATION: derive a floor for severity from the defect text (does not run / leaks / smokes / unsafe ⇒ material), require provenance to lower a severity or remove a defect, and hash-chain the defect list."),
    ("F-62", "FACT", "01 (merchandising)", "G-11: (a) `_VERIFY_CLAIMS` is skipped as soon as ANY fact is verified, so an unrelated verified VIN unlocks 'Inspected and certified. Tested and working.'; "
     "(b) a view fact may carry a `provenance_id` the inventory fact does not have (the check only runs when the inventory fact has one).",
     "RECOMMENDATION: a verification word needs a verified fact whose key matches the claim; a view provenance_id must equal the inventory's, never appear from nowhere."),
    ("F-63", "FACT", "01 (mission, campaign, valuation)", "G-11: NaN and Infinity pass every comparison-based rule. Mission: `available_to_deploy`, `capital_deployed`, a leg's `cash_at_risk` = NaN or inf bypasses the ledger arithmetic and the over-spend check. "
     "Campaign: `max_price_usd` NaN and an autopilot with NaN limits validate (effectively unlimited). Valuation: NaN/inf ranges validate. (8 cases)",
     "RECOMMENDATION: reject non-finite numbers in each validator (math.isfinite) or in a shared pre-pass."),
    ("F-64", "FACT", "01 (mission)", "G-11: the plan's numbers are not derived. A null projection with `remaining_gap: 0` validates (the gap is only checked when `projected_week.likely` is known), and a projection of $9,500 validates "
     "beside legs whose expected nets add up to $455 (just keep `remaining_gap` consistent with it).",
     "RECOMMENDATION: projected_week.{low,likely,high} must equal the sum over legs (or be null with a reason), and remaining_gap must be null whenever the projection is."),
    ("F-65", "FACT", "01 (mission)", "G-11: plan coherence is not checked: DEPLOY with no legs; HOLD or UNKNOWN that still commit cash (only DO_NOT_SPEND is checked); legs needing 7.5 hours with `hours_available` 2; "
     "an inverted period; two legs sharing a scorecard id; a ledger `as_of` in 2020; DEPLOY while the principal is impaired (8 cases).",
     "RECOMMENDATION: add these invariants to `plan_errors`; stale legs need a `valid_until` the validator can compare with now."),
    ("F-66", "FACT", "01 (campaign)", "G-11: `may_run` ignores expiry: a RECOMMEND/ACTIVE campaign whose `stop_conditions.expires_at` or `limits.expires_at` is in the past still runs; `may_run({})` raises KeyError instead of False; "
     "a BOUNDED_AUTOPILOT whose `limits.expires_at` is already past validates. (Autopilot itself is correctly refused: `may_run` is False and the schema demands limits.)",
     "RECOMMENDATION: `may_run` validates first and checks expiry and `max_matches`; reject past expiries at validation."),
    ("F-67", "FACT", "01 (valuation)", "G-11: the ranges are not related to each other or to the evidence: fast_sale above suggested_list, as_is above after_repair, a zero-width 'range' (1234..1234, the fake precise number the schema title forbids), 1..1,000,000, "
     "confidence 'high' on ONE sold_comp whose ref is 'x', 'medium' on priors only, a home at 'high' on a single record.",
     "RECOMMENDATION: order checks (fast_sale <= likely_sale <= suggested_list; as_is <= after_repair), a minimum relative width, and a count/provenance requirement per confidence level."),
    ("F-68", "FACT", "01 (valuation)", "G-11: `not_an_appraisal` is enforced but free text is not: a description 'Certified appraised value $5,000' and an evidence note 'verified and guaranteed by appraiser' validate; "
     "`unknowns` is not reconciled with the null ranges (a null `as_is` with `unknowns: []` validates).",
     "RECOMMENDATION: run the merchandising claim lint over description/note and require every null range key in `unknowns`."),
    ("F-69", "FACT", "01 (card)", "G-13: regression from A-35: with `time_to_cash_days` missing, `cash_multiple` is now UNKNOWN. A multiple is net/cash and needs no days; "
     "the test `test_each_derived_field_is_unknown_when_only_its_own_input_is_missing` pinned that (passed through G-12). Fails safe (UNKNOWN, never a wrong number) but loses information.",
     "RECOMMENDATION: treat only malformed (not absent) days as poisoning the multiple; or rule that missing days means UNKNOWN multiple and I will restate the test."),
    ("F-70", "FACT", "01 (cli)", "G-15 cold start: `mbos queue` prints the areq and payload hash but never the `item_id`, and no command lists items, yet `mbos card ITEM_ID` / `show` / `outcome` need it. "
     "A fresh operator must copy ids from the `mbos worker` JSON output or query Postgres (psql is not installed).",
     "RECOMMENDATION: print `item  itm_...` in each `mbos queue` entry (and/or add `mbos items`)."),
    ("F-71", "FACT", "01 (runbook)", "G-15 cold start: RUNBOOK says the Operator UI renders the card at `/item/<id>` but gives no command, and the UI is not in the coordinator head (it lives on `research/agent-06-communications`, `python -m operator_ui serve`). "
     "RUNBOOK section 2 also hard-codes the `agent-01-coordinator` worktree path.",
     "RECOMMENDATION: add an Operator UI section to RUNBOOK (archive-install recipe from LANE_06 handoff, MBOS_OPERATOR_PIN, port 8765) once 01 integrates the UI; use `<your worktree>` in section 2."),
    ("F-72", "FACT", "06 (operator_ui)", "G-16: `/numbers/capital` replay with the SAME nonce but a different amount is idempotent (only the first is recorded) yet the page says `Fund of $900.00 recorded` while the ledger moved by $7. The success message echoes the request, not the receipt.",
     "REPRO: `cd qa && ../.venv/bin/python -m pytest -q tests/numbers -k changed_amount -rx`. RECOMMENDATION: build the message from the stored receipt/after_state, or refuse a reused key whose payload differs."),
    ("F-73", "FACT", "06 (operator_ui)", "G-16: a non-ASCII `csrf` or `pin` (e.g. `é`) makes `secrets.compare_digest` raise TypeError in `_check_csrf` / `_numbers_gate` (also `_note_gate`, `add_note`): the handler thread dies and the client gets a dropped connection instead of the refusal page. Nothing is written (fail-closed), P3.",
     "REPRO: `-k non_ascii`. RECOMMENDATION: compare `.encode()` bytes, or catch TypeError as a refusal."),
    ("F-74", "FACT", "06 (operator_ui)", "G-16: `numbers_view.render_page` pre-fills the form with `value or ''`, so an explicit 0 (target or hours) renders as an empty box; saving the untouched form silently turns Michael's 0 into UNKNOWN (a receipted change nobody asked for). P2.",
     "REPRO: `-k zero_survives`. RECOMMENDATION: use `'' if v is None else v`."),
    ("F-75", "FACT", "06 (operator_ui)", "G-16: `parse_amount` accepts Unicode digits (`٣٠٠`, fullwidth `９`), repeated `$` (`$$5`) and comma anywhere (`1,5,0,0` = 1500), though its own message says 'a plain number like 1500 or 12.50'. NaN/Infinity/negative/exponent/over-cap/3-decimals are all refused. P3.",
     "REPRO: `-k amount_parser_is_strict`. RECOMMENDATION: `re.ASCII`, strip one leading `$`, require 3-digit comma groups."),
    ("F-76", "INFER", "06 (+ Michael: sane bound)", "G-16: one POST can fund $10,000,000.00 (the cap is per transaction, there is no cumulative bound and no confirm step), making a dry-run `available_to_deploy` of $10M for a one-person flipping business. Not exploitable without the PIN; a fat-finger guard is missing. P3.",
     "REPRO: `-k sane_bounds`. RECOMMENDATION: a much lower per-transaction cap or a confirm step above a Michael-owned threshold (DECISIONS item)."),
    ("F-77", "FACT", "06 (operator_ui)", "G-16: no attempt limit or lockout on the step-up PIN for My numbers (or approvals/notes): 40 wrong PINs, then the right PIN still works at once. Mitigated by the 127.0.0.1 bind and Host check. P3.",
     "REPRO: `-k throttled`. RECOMMENDATION: per-process failure counter with exponential delay."),
    ("F-78", "FACT", "04 (lane D)", "G-16: `mbos.set_mission/capital_fund/capital_withdraw` take the actor as a free JSON argument and only check the LOGIN's role; the approver login can record `{type: agent}`. 'An agent actor is refused' therefore rests on the UI code setting `human:michael`, not on the database. Non-approver logins (reader, state_mcp, gateway, policy, relay, dbos) ARE refused for the functions, direct INSERTs and forged `capital_fund` receipts (verified, passing tests).",
     "REPRO: `-k agent_actor_from_the_owner_login`. RECOMMENDATION: require `p_actor->>'type' = 'human'` in these three functions."),
    ("F-16", "FACT", "01", "FIXED by A-10 (verified at 82632c3: a normal install finds its contracts and operator profile). Original finding: Agent 01's package only finds the contracts by a path relative to the source tree. "
     "With a normal (non-editable) `pip install`, 94 of its 109 tests fail or error with `docs/research/contracts "
     "not found; set MBOS_CONTRACTS_DIR`. With that variable set, 108 pass and 1 is skipped "
     "([BUILD_VERIFICATION](BUILD_VERIFICATION.md)).",
     "RECOMMENDATION: ship the contracts as package data (as 02 and 05 do), or fail at import with clear setup "
     "instructions. Packaging for deployment needs this."),
    ("F-17", "FACT", "launcher / all lanes", "The git identity is stored in the SHARED `.git/config` "
     "(`extensions.worktreeConfig` is unset), so the launcher's per-agent identity reassertion overwrites every "
     "worktree. Agent 01's commits acb6f3b, c6c5ad4, 7ed5705 and bed7609 are authored 'Agent 07 Marketing'. "
     "Commit provenance across all branches is unreliable.",
     "RECOMMENDATION (launcher owner; not changed by 07): `git config extensions.worktreeConfig true` plus "
     "`git config --worktree user.name/email` per worktree in `~/bin/mbos-agent`. Note the misattribution in "
     "affected receipts. History is not rewritten."),
]


def cmd_contracts(drift_ref):
    rep = run_contract_checks(CONTRACTS_DIR, drift_ref=drift_ref)
    for c in rep.checks:
        print(("PASS " if c.passed else "FAIL ") + c.name + (f" — {c.detail}" if c.detail else ""))
    for g in run_gap_probes():
        print(("OK   " if g.passed else "GAP  ") + g.name + f" — {g.detail}")
    return rep


def cmd_e2e(out_dir: pathlib.Path):
    with tempfile.TemporaryDirectory() as td:
        h = build(pathlib.Path(td) / "e2e")
        results = run_all(h)
        sections = [report.item_section(h, r["item_id"], r["fixture"]) for r in results]
        pk_out = out_dir / "packets"
        if pk_out.exists():
            shutil.rmtree(pk_out)
        shutil.copytree(h.workdir / "packets", pk_out)
        impl = h.implementations
        chain = h.store.verify_chain()
        n_exec = len(h.store.receipts(type="ACTION_EXECUTED"))
    body = [
        "# End-to-end dry-run result: one flip and one service",
        "",
        "> Generated by `python -m mbos_qa e2e` (Agent 07, lane G). **Fully synthetic fixtures. DRY-RUN.** "
        "Nothing was sent, posted, purchased or paid. Owner decisions in this run are **simulated by the fixture**, "
        "not made by Michael. A fixed clock and seeded IDs make this file reproducible byte for byte.",
        "",
        "## Implementations under test",
        "",
        "| Lane | Implementation |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in impl.items()],
        "",
        f"**Ledger:** `verify_chain` {'PASS' if chain.ok else 'FAIL'} over {chain.checked} receipts. "
        f"{n_exec} dry-run executions, and every one has `dry_run=true`.",
        "",
        "**Manual-assist packets:** [`packets/`](packets/)",
        "",
        *sections,
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "E2E_REPORT.md").write_text("\n".join(body))
    print(f"wrote {out_dir / 'E2E_REPORT.md'} and {len(list(pk_out.glob('*.md')))} packets")
    return results, chain.ok


def cmd_tests() -> tuple[int, list[tuple[str, str, str, str]]]:
    with tempfile.TemporaryDirectory() as td:
        xml = pathlib.Path(td) / "junit.xml"
        env = dict(os.environ, PYTHONPATH=str(QA_ROOT))
        rc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}",
                             "tests", "--ignore=tests/card", "--ignore=tests/spec", "--ignore=tests/followup", "--ignore=tests/engine", "--ignore=tests/seams", "--ignore=tests/numbers"], cwd=QA_ROOT, env=env).returncode
        rows = []
        for tc in ET.parse(xml).getroot().iter("testcase"):
            outcome = "passed"
            for child in tc:
                if child.tag in ("failure", "error"):
                    outcome = "FAILED"
                elif child.tag == "skipped":
                    outcome = "xfail (known gap)" if "xfail" in (child.get("type", "") + child.get("message", "")) else "skipped"
            rows.append((tc.get("classname").split(".")[-1], tc.get("name"), outcome, ""))
    return rc, rows


SPEC_GROUPS = OrderedDict([(f"test_spec_a{n:02d}", title) for n, title in enumerate([
    "A1 atomic state + receipt", "A2 insert-only (agent_write role and owner; UPDATE/DELETE/TRUNCATE)",
    "A3 chain verification (01 verifier + ADR-0010 reference) and tamper",
    "A4 provenance resolution (independent + 01 audit)", "A5 hard kill mid-ACT → DBOS restart → effector exactly once",
    "A6 YES / NO / MODIFY / HOLD (DBOS approval gate, restart)", "A7 100% dry-run (receipts, effector calls, DB CHECK)",
    "A8 LLM spend cap (LedgerLLMBudget)", "A9 PANIC fail-closed (L1/L2/L3, unreadable switch)",
    "A10 contract conformance (pinned contracts, format-checked)"], start=1)]
                         + [("test_spec_g_marketing", "G1–G4 marketing on the real approval path (lane-07 planner)")])


RC_FINDING_BY_TEST = {  # failing/xfail case (substring) → finding. Mapping is data, so the verdict is auditable.
    "test_spec_a09_panic": "F-24", "test_spec_a05_crash::test_kill_mid_act_settles": "F-25",
    "a_yes_the_policy_will_refuse": "F-40", "test_a_pdp_denied_proposal_never_leaves": "F-23",
}


CARD_CRASH_IDS = {"enrichment-is-string", "enrichment-is-number", "block-is-list", "block-is-string", "recent-activity-not-iterable",
                  "why-number", "peak-months-strings", "peak-months-nested", "risks-not-list", "risks-null-entries", "money-as-string"}
CARD_REQ = OrderedDict([
    ("test_card_honesty", "No fabrication: no/malformed enrichment → UNKNOWN, listed in `unknowns`; values validated"),
    ("test_card_lint", "Elementary-advice lint (plans, risks) unless sourced and model-specific"),
    ("test_card_trail_timeline", "Trail = receipts 1:1 with input provenance; timeline only with events"),
    ("test_card_determinism", "Determinism: stable, order-independent, meaningful card_hash"),
    ("test_card_hostile", "Hostile listing text: contract, recommendation and text view"),
    ("test_card_authority", "Decision authority: derived recommendation, no authority, read-only"),
    ("test_card_backends", "Real flows on the backend: trail vs ledger, enrichment, poison listings, F-23 regression"),
    ("test_card_adr0012", "ADR-0012 card fields: honest UNKNOWN, class boundaries as data, malformed numbers, no profit floor (G-10)"),
    ("test_product_seams", "Product seams (ADR-0013): merchandising lint, mission plan, campaign autonomy, valuation honesty (G-11)"),
    ("test_engine_adr0012", "ADR-0012 engine: no min_profit constant, three training examples, cash never assumed, malformed refused (G-10)"),
])


def _card_finding(module: str, name: str) -> str:
    n = name
    if "test_malformed_enrichment_degrades" in n:
        pid = n[n.index("[") + 1:-1]
        return "F-26" if pid in CARD_CRASH_IDS else "F-27"
    if "one_malformed_enrichment_block" in n:
        return "F-27" if "bad-provenance" in n else "F-26"
    table = [("euphemisms_for_a_material", "F-59"), ("obfuscated_overstatements", "F-59"), ("visible_in_the_headline", "F-60"), ("label_cannot_overstate", "F-60"),
             ("downgrading_or_deleting", "F-61"), ("defect_cannot_vanish", "F-61"), ("invent_provenance", "F-62"), ("verification_claim_needs", "F-62"),
             ("non_finite_numbers", "F-63"), ("projection_and_the_gap", "F-64"), ("plan_must_be_coherent", "F-65"), ("expired_or_invalid_campaign", "F-66"),
             ("autopilot_limits_must_not", "F-66"), ("internally_consistent", "F-67"), ("never_claims_to_be_an_appraisal", "F-68"),
             ("malformed_number_never_crashes", "F-52"), ("nonsensical_cash_or_time", "F-53"), ("malformed_cash_context", "F-51"),
             ("malformed_class_thresholds", "F-54"), ("impossible_liquidity", "F-55"), ("gross_profit_range_is_ordered", "F-56"),
             ("single_michael_stated_source", "F-57"), ("wrong_buy_today", "F-58"), ("fuzzed_enrichment", "F-26"), ("lane_values_are_validated", "F-28"), ("impossible_lane_values", "F-28"),
             ("unordered_resale", "F-28"), ("date_formats_that_are_not_iso", "F-28"), ("headline_status", "F-31"), ("lane_why_lines", "F-30"), ("why_lines_from_a_lane", "F-29"),
             ("lint", "F-30"), ("elementary", "F-30"), ("junk_source", "F-30"), ("model_specific", "F-30"), ("basis_fact", "F-30"),
             ("generic_advice", "F-30"), ("contact_sent", "F-31"), ("dry_run", "F-31"), ("contact_approved", "F-32"),
             ("seller_reply", "F-32"), ("recorded_seller_reply", "F-32"), ("attribution", "F-32"), ("closed", "F-32"),
             ("other_items", "F-38"), ("independent_of_receipt", "F-33"), ("tampered_card", "F-34"),
             ("poison_listing", "F-36"), ("injection_flag", "F-37"), ("vocabulary", "F-39"),
             ("huge_listing", "F-35"), ("forge_or_corrupt", "F-35"), ("hostile_city", "F-35"), ("hostile_title_through", "F-35")]
    if "keeps_the_card_valid" in n and "null-byte" in n:
        return "F-36"
    for needle, fid in table:
        if needle in n:
            return fid
    return "—"


def _run_pytest(label, env_extra, args):
    with tempfile.TemporaryDirectory() as td:
        xml = pathlib.Path(td) / "j.xml"
        env = {k: v for k, v in os.environ.items() if not k.startswith("MBOS_QA_")}
        env.update(PYTHONPATH=str(QA_ROOT), **env_extra)
        t0 = time.time()
        subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=240", "-W", "ignore",
                        f"--junitxml={xml}", *args], cwd=QA_ROOT, env=env)
        rows = []
        for tc in ET.parse(xml).getroot().iter("testcase"):
            outcome = "passed"
            for ch in tc:
                if ch.tag in ("failure", "error"):
                    outcome = "FAILED"
                elif ch.tag == "skipped":
                    outcome = "skipped"
            rows.append((label, tc.get("classname").split(".")[-1], tc.get("name"), outcome))
        return rows, round(time.time() - t0)


def cmd_card() -> int:

    rows, secs = [], {}
    r, secs["pure"] = _run_pytest("pure", {}, ["tests/card", "--ignore=tests/card/test_card_backends.py"])
    rows += r
    r, secs["engine"] = _run_pytest("engine (lane C pinned)", {}, ["tests/engine"])
    rows += r
    r, secs["seams"] = _run_pytest("product seams", {}, ["tests/seams"])
    rows += r
    r, secs["numbers"] = _run_pytest("My numbers (F-22, G-16)", {}, ["tests/numbers"])
    rows += r
    base = {"MBOS_QA_IMPL": "mbos_qa.impl_spine:build"}
    r, secs["reference"] = _run_pytest("reference backend", base, ["tests/card/test_card_backends.py"])
    rows += r
    r, secs["lane D+E"] = _run_pytest("lane D + lane E", {**base, "MBOS_QA_STATE_BACKEND": "lane_d", "MBOS_QA_GATEWAY_MODE": "lane_e"},
                                      ["tests/card/test_card_backends.py"])
    rows += r
    pins = json.loads((QA_ROOT / "impl_lane_pins.json").read_text())
    failed = [x for x in rows if x[3] == "FAILED"]
    passed = [x for x in rows if x[3] == "passed"]
    L = ["# Deal Sniffer card acceptance (task G-05, ADR-0011)", "",
         f"> Generated by `python -m mbos_qa card`. Adversarial suite against `mbos.card` at the pinned Agent 01 commit "
         f"`{pins['mbos_01'][:7]}`, run in three configurations: PURE (no database; synthetic-but-valid histories built "
         f"from the frozen contract examples), the REFERENCE backend, and the release-candidate stack (Agent 04 schema "
         f"`{pins['lane_d_04'][:7]}`, Agent 05 gateway `{pins['lane_e_05'][:7]}`). Cards are validated INDEPENDENTLY of "
         "01's `validate_card`: with this lane's byte-pinned `ext/card.schema.json` (format checks on) plus the honesty "
         "rules re-implemented from the ADR. DRY-RUN only.", "",
         f"**{len(passed)} passed, {len(failed)} failed** of {len(rows)} cases "
         f"({', '.join(f'{k} {v}s' for k, v in secs.items())}). Every failure is mapped to a finding; unmapped: "
         f"{[x[2] for x in failed if _card_finding(x[1], x[2]) == '—'] or 'none'}.", "",
         "## Requirement results", "", "| Requirement (from G-05) | Result | Cases | Failing → findings |", "|---|---|---:|---|"]
    for prefix, title in CARD_REQ.items():
        g = [x for x in rows if x[1] == prefix]
        fl = [x for x in g if x[3] == "FAILED"]
        fids = sorted({_card_finding(x[1], x[2]) for x in fl})
        L.append(f"| {title} | **{'FAIL' if fl else 'PASS'}** | {len(g)} ({len(fl)} fail) | {', '.join(fids) or '—'} |")
    L += ["", "## What holds (verified, not assumed)", "",
          "- **NEGOTIATING / QUALIFIED are never invented:** 200 adversarial histories (words, kinds and decisions chosen to "
          "tempt the mapper) and 9 real flows on both backends produce neither stage.",
          "- **Trail = ledger 1:1 on real flows** (pending, service, maybe, pass, YES→ACTED, NO, HOLD, MODIFY, freeze→FAILED), on the "
          "reference backend and on lane D+E, with the trail equal to the union of the receipts carrying the item's id and those tied to "
          "its action requests; every row cites provenance that resolves in the database.",
          "- **Read-only:** building, validating and rendering a card changes no row in 8 ledger tables and the chain still verifies.",
          "- **Determinism that works:** stable across processes and PYTHONHASHSEED, independent of generation time, key order and "
          "`850` vs `850.0`, equal to an independent MBOS-CJSON-1 recomputation.",
          "- **Authority:** no decision/approval fields, the recommendation uses its own vocabulary (except HOLD, F-39), is unchanged "
          "by hostile listing text or by enrichment trying to override it, and a pending request is never shown as decided.",
          "- **Enrichment seam:** a lane's data round-trips with its provenance and appears in the trail; two writes to the same block "
          "keep the latest (atomic, D-16); the F-23 fix (a PDP-denied proposal is shown as blocked, not awaiting Michael) holds on lane E.",
          "", "## Failing cases by finding", "", "| Finding | Cases (configuration) |", "|---|---|"]
    by = {}
    for lab, mod, name, out in rows:
        if out == "FAILED":
            short = name.replace("test_", "", 1)
            short = (short[:44] + ("…" + short[short.index("["):] if "[" in short and len(short) > 44 else "")) if len(short) > 44 else short
            by.setdefault(_card_finding(mod, name), []).append(f"`{short}` ({lab})")
    for fid, cases in sorted(by.items()):
        L.append(f"| {fid} | {'<br>'.join(cases[:10])}{'<br>… +' + str(len(cases) - 10) + ' more' if len(cases) > 10 else ''} |")
    L += ["", "Finding text, severity and recommendations are in [ACCEPTANCE_REPORT.md](ACCEPTANCE_REPORT.md) (F-26 … F-39).", "",
          "## Every case", "", "| Config | Module | Test | Outcome | Finding |", "|---|---|---|---|---|"]
    L += [f"| {lab} | {mod} | `{name[:90]}` | {out} | {_card_finding(mod, name) if out == 'FAILED' else ''} |" for lab, mod, name, out in rows]
    (OUT / "CARD_ACCEPTANCE.md").write_text("\n".join(L) + "\n")
    print(f"wrote {OUT / 'CARD_ACCEPTANCE.md'}: {len(passed)} passed, {len(failed)} failed")
    return 0 if not failed else 1


def _finding_for(module: str, test: str) -> str:
    key = f"{module}::{test}"
    for needle, fid in RC_FINDING_BY_TEST.items():
        if needle in key or needle in test:
            return fid
    return "—"


def cmd_spine(release: bool = False) -> int:
    if release:
        os.environ["MBOS_QA_STATE_BACKEND"], os.environ["MBOS_QA_GATEWAY_MODE"] = "lane_d", "lane_e"
    from . import impl_spine

    with tempfile.TemporaryDirectory() as td:
        xml = pathlib.Path(td) / "junit.xml"
        env = dict(os.environ, PYTHONPATH=str(QA_ROOT), MBOS_QA_IMPL="mbos_qa.impl_spine:build")
        t0 = time.time()
        pytest_rc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=240",
                                    "-W", "ignore", f"--junitxml={xml}", "tests/spec"], cwd=QA_ROOT, env=env).returncode
        secs = round(time.time() - t0)
        rows = []
        for tc in ET.parse(xml).getroot().iter("testcase"):
            outcome, note = "passed", ""
            for child in tc:
                if child.tag in ("failure", "error"):
                    outcome, note = "FAILED", (child.get("message") or "")[:160]
                elif child.tag == "skipped":
                    xf = "xfail" in (child.get("type", "") + child.get("message", ""))
                    outcome = "xfail (known gap)" if xf else "skipped"
                    note = (child.get("message") or "")[:200]
                elif child.tag == "properties":
                    note = "; ".join(f"{p.get('name')}: {p.get('value')}" for p in child)
            rows.append((tc.get("classname").split(".")[-1], tc.get("name"), outcome, note))
    passed = sum(r[2] == "passed" for r in rows)
    failed = sum(r[2] == "FAILED" for r in rows)
    xfailed = sum(r[2].startswith("xfail") for r in rows)
    na = sum(r[2] == "skipped" for r in rows)
    title = "Wave-two RELEASE CANDIDATE verdict (task G-04)" if release else "A1–A10 against the REAL spine (task G-02)"
    L = [f"# {title}", "",
         f"> Generated by `python -m mbos_qa spine{' --rc' if release else ''}`. **Implementation under test:** "
         f"{impl_spine.IMPLEMENTATION}. Pins: `qa/impl_spine_PIN` = `{impl_spine.PIN}`; `qa/impl_lane_pins.json`. "
         "Nothing here is mocked: every state change, decision, guard check and receipt comes from the real lanes. The "
         "adapter (`mbos_qa/impl_spine.py`) only boots PostgreSQL/DBOS, feeds 01's own fixture listings, reads state "
         "back, and provides superuser fault/tamper hooks. DRY-RUN only.", ""]
    if release:
        blockers = sorted({_finding_for(m_, n_) for m_, n_, o_, _ in rows if o_ == "FAILED"} - {"—"})
        unmapped = [n_ for m_, n_, o_, _ in rows if o_ == "FAILED" and _finding_for(m_, n_) == "—"]
        verdict = "READY" if not failed else "NOT READY"
        L += [f"## Verdict: **{verdict}**", "",
              f"{passed} passed, {failed} failed, {xfailed} strict-xfail known gaps, {na} not applicable; "
              f"{len(rows)} cases, {secs}s.", ""]
        L += ["**Scope of this verdict.** READY means: for the DRY-RUN MVP stack above, every acceptance test in this suite passes, "
              "stably, and the safety invariants hold. It is not evidence about anything that does not exist in the stack: live "
              "sending or publishing (there is no live effector; the provider is a dry-run simulator), the LiteLLM-enforced LLM cap "
              "(A8 is tested against `LedgerLLMBudget`), real egress cut / credential revocation on PANIC, lane C's real scoring "
              "engine (the stack uses 01's placeholder scorer), real discovery sources, or the Operator UI. Card quality is judged "
              "separately in [CARD_ACCEPTANCE.md](CARD_ACCEPTANCE.md), which still has open items (it is a read-only view, not a safety invariant).", ""]
        if failed:
            L += ["Blocking findings: " + ", ".join(blockers) + (f"; **unmapped failures: {unmapped}**" if unmapped else "")
                  + ". Details in [ACCEPTANCE_REPORT.md](ACCEPTANCE_REPORT.md) (findings table).", ""]
        if xfailed:
            L += [f"{xfailed} case(s) are strict xfails tied to open findings (they must fail while the finding is open, "
                  "and turn into failures when it closes, so the marker is removed rather than forgotten).", ""]
    else:
        L += [f"**Result: {'PASS' if pytest_rc == 0 and not failed else 'FAIL'}.** {passed} passed, {failed} failed, "
              f"{xfailed} strict-xfail known gaps, {na} not applicable; {len(rows)} cases, {secs}s.", ""]
    if release:
        safety = ["test_spec_a01", "test_spec_a02", "test_spec_a03", "test_spec_a04", "test_spec_a05", "test_spec_a07",
                  "test_spec_a09", "test_spec_a10"]
        safe_ok = all(not any(r[2] == "FAILED" for r in rows if r[0].startswith(p)) and any(r[0].startswith(p) for r in rows)
                      for p in safety)
        L += ["## Safety invariants", "",
              f"**{'HOLD' if safe_ok else 'BROKEN'}** (A1 atomicity, A2 insert-only, A3 chain, A4 provenance, A5 no duplicate effect, "
              "A7 dry-run only, A9 fail-closed PANIC, A10 contract conformance). Nothing left the system, no effect was duplicated, "
              "no denied approval can fire later, and the receipt chain verifies in lane D and in the ADR-0010 reference alone.", "",
              "## Still red: exactly what, and who owns it", "", "| Finding | Owner | Impact | What closes it |", "|---|---|---|---|"]
        owners = {"F-40": ("01 (`spine.decide`) + 05 (policy)", "Fails SAFE: nothing executes. Michael's YES on a publishing request given WITHOUT step-up is accepted, "
                           "then refused at the gateway (`STEP_UP_REQUIRED`); the item ends FAILED and his approval is lost. With step-up it executes once.",
                           "`decide` refuses a YES that lacks the step-up the PDP stamped on the request; a guard-refused request settles failed, not `approved`.")}
        reds = sorted({_finding_for(m_, n_) for m_, n_, o_, _ in rows if o_ == "FAILED"})
        for f in reds:
            o = owners.get(f, ("?", "see ACCEPTANCE_REPORT.md", "see ACCEPTANCE_REPORT.md"))
            L.append(f"| {f} | {o[0]} | {o[1]} | {o[2]} |")
        if not reds:
            L.append("| — | — | nothing red | — |")
        L += ["", "## Closed since the previous verdict (NOT READY, 88/9/6)", "", "| Finding | Closed by | Evidence on this stack |", "|---|---|---|",
              "| F-24 stale approval executes after a freeze | 05 E-13 | A9 8/8 incl. the replay regression |",
              "| F-25 crash mid-ACT | R22 + 05 E-13 | A5 5/5: no duplicate; truthful settlement (executed after a send, failed+RECONCILED before) |",
              "| F-22 no publish grant | 05 E-13 | G1/G4 publish cases pass (with step-up) |",
              "| F-23 PDP denial leaves the item awaiting Michael | 01 R21 | an ungranted capability leaves no live request and the item not awaiting |",
              "| F-40 a YES the policy will refuse is accepted, then lost | 01 R24 + 05 E-15 | `test_a_yes_the_policy_will_refuse_is_refused_when_it_is_given` passes: a YES without step-up is refused at decision time |",
              "| F-41 broad propose grants on one shared identity | 05 w1.8 + 01 lane tags | policy data: nobody holds money.payment.send / price.change / commit.external; a publishing proposal is stamped `proposed_by: agent-07-marketing`, email falls back to the spine identity |",
              "| F-16 packaging, F-18/19/20/21 | 01 A-10, A-13, … | verified at earlier pins |",
              "", ("Open in this suite: " + ", ".join(reds) + "." if reds else "Nothing is open in this acceptance suite.")
              + " Card defects are tracked separately in [CARD_ACCEPTANCE.md](CARD_ACCEPTANCE.md).", ""]
    L += ["| Acceptance test | Result | Cases |", "|---|---|---:|"]
    for prefix, title_ in SPEC_GROUPS.items():
        g = [r for r in rows if r[0] == prefix or r[0].startswith(prefix + "_")]
        xf = sum(r[2].startswith("xfail") for r in g)
        sk = sum(r[2] == "skipped" for r in g)
        nf = sum(r[2] == "FAILED" for r in g)
        res = f"FAIL ({nf} of {len(g)})" if nf else (
            ("PASS" + (f" ({xf} known gap)" if xf else "") + (f" ({sk} not applicable)" if sk else "")) if g else "NOT RUN")
        L.append(f"| {title_} | **{res}** | {len(g)} |")
    if release:
        L += ["", "## Failing cases by finding", "", "| Finding | Cases |", "|---|---|"]
        by = {}
        for m_, n_, o_, _ in rows:
            if o_ == "FAILED":
                by.setdefault(_finding_for(m_, n_), []).append(f"`{n_}`")
        L += [f"| {k} | {'<br>'.join(v)} |" for k, v in sorted(by.items())]
    L += ["", "## What is real vs. still pending", ""]
    if release:
        L += ["- **Real:** Agent 01's spine and DBOS workflows (`mbos` @ the pin), Agent 04's canonical schema "
              "(`state_backend=lane_d`, migrated by lane D's own migrator, with roles and pgvector), and Agent 05's real "
              "`ActionGateway`, PANIC state, PDP and policy (`gateway_mode=lane_e`, the whole `policy/` directory).",
              "- **Still 01's reference components even here:** `LedgerLLMBudget` (A8; LiteLLM is not wired), the dry-run "
              "effector (05's simulated provider keeps its delivery record in process), the placeholder scorer, and "
              "fixture source adapters. Real egress cut / credential revocation (L3 side effects) are not built.",
              "- **Not run on this stack:** one reference-only test (a ReferenceGateway built around a live effector) is "
              "skipped with its reason; the same property is covered by lane E's own suite (BUILD_VERIFICATION)."]
    else:
        L += ["- **Real (01's code):** DBOS workflows, `spine.decide`, the reference gateway (8 checks) and "
              "`DryRunEffector`, the Postgres ledger with insert-only triggers, `CHECK` constraints and the MBOS-RH-1 chain, "
              "`TableKillSwitch`, `LedgerLLMBudget`, and `audit`.",
              f"- This run used `state_backend={impl_spine.STATE_BACKEND}`, `gateway_mode={impl_spine.GATEWAY_MODE}`. The "
              "wave-two stack is judged by `python -m mbos_qa spine --rc` (RELEASE_CANDIDATE.md)."]
    L += ["- **Crash/restart (A5, A6):** a real child process killed with `os._exit(137)`, then a second process "
          "whose `DBOS.launch()` recovers the workflow.", "",
          "## Every case", "", "| Module | Test | Outcome | Finding | Note |", "|---|---|---|---|---|"]
    L += [f"| {m_} | `{n_}` | {o_} | {_finding_for(m_, n_) if o_ in ('FAILED',) or o_.startswith('xfail') else ''} | "
          f"{note.replace('|', '/')} |" for m_, n_, o_, note in rows]
    out = OUT / ("RELEASE_CANDIDATE.md" if release else "SPINE_ACCEPTANCE.md")
    out.write_text("\n".join(L) + "\n")
    print(f"wrote {out}: {passed} passed, {failed} failed, {xfailed} xfail")
    return 0 if pytest_rc == 0 and not failed else 1


FINDING_STATUS = {  # verified by the suites at the pins in qa/impl_lane_pins.json (G-12 re-run)
    "F-22": "FIXED", "F-23": "FIXED", "F-24": "FIXED", "F-25": "FIXED (R22)", "F-40": "FIXED", "F-41": "FIXED", "F-42": "FIXED (G-09, 01 100d2ed)", "F-43": "FIXED (G-09, 01 100d2ed)", "F-44": "FIXED (G-09, 01 100d2ed)", "F-45": "FIXED (G-09, 01 100d2ed)", "F-46": "FIXED (G-09)", "F-47": "FIXED (G-09)", "F-48": "FIXED (G-09; residual F-50)", "F-49": "FIXED (G-09)", "F-50": "OPEN", "F-51": "FIXED (G-12, A-34)", "F-52": "FIXED (G-13, A-35 da72f5c)", "F-53": "FIXED (G-13, A-35 da72f5c)", "F-54": "FIXED (G-12, A-34)", "F-55": "FIXED (G-13, A-35 da72f5c)", "F-56": "FIXED (G-13, A-35 da72f5c)", "F-57": "FIXED (G-12, C-23 3eb358f)", "F-58": "FIXED (G-12, C-23 3eb358f)", "F-59": "FIXED (G-12, A-32)", "F-60": "FIXED (G-12, A-32)", "F-69": "FIXED (G-14, 01 944f8e4)", "F-70": "OPEN", "F-71": "OPEN", "F-72": "OPEN", "F-73": "OPEN", "F-74": "OPEN", "F-75": "OPEN", "F-76": "OPEN", "F-77": "OPEN", "F-78": "OPEN", "F-61": "FIXED (G-13, A-35 da72f5c)", "F-62": "FIXED (G-13, A-35 da72f5c)", "F-63": "FIXED (G-12, A-33)", "F-64": "FIXED (G-12, A-33)", "F-65": "FIXED (G-13, A-35 da72f5c)", "F-66": "FIXED (G-13, A-35 da72f5c)", "F-67": "FIXED (G-14, 01 944f8e4)", "F-68": "FIXED (G-13, A-35 da72f5c)",
    "F-16": "FIXED", "F-18": "FIXED", "F-19": "FIXED", "F-20": "FIXED", "F-21": "FIXED",
    "F-26": "FIXED", "F-27": "FIXED (an uncheckable risk is dropped, never left invalid)",
    "F-28": "FIXED (ISO strings only; a bare number such as 20261005 is UNKNOWN; valid dates still display)",
    "F-29": "FIXED", "F-30": "FIXED (ADR-0011 amended: with no model-specific marker in the contract, nothing elementary-phrased can pass; a rejected claim leaves a trace in `unknowns`)",
    "F-31": "FIXED (headline now carries the DRY-RUN marker)",
    "F-32": "FIXED", "F-33": "FIXED", "F-34": "FIXED", "F-35": "FIXED",
    "F-36": "FIXED (the good listings behind a NUL ingest; the poison one is retried scrubbed and flagged needs_review; both backends)",
    "F-37": "FIXED", "F-38": "FIXED", "F-39": "ACCEPTED (R25)",
    "F-13": "FIXED", "F-14": "FIXED",
}


def write_acceptance_report(contract_rep, gaps, test_rc, rows, e2e_ok, drift_ref):
    pin = json.loads((CONTRACTS_DIR / "PIN.json").read_text())
    lines = [
        "# Acceptance report: A1–A10 (+ G), wave one",
        "",
        "> Generated by `python -m mbos_qa run` (Agent 07, independent QA / integration lane G). "
        "Every component not owned by this lane is a **clearly marked MOCK** that conforms to the frozen contracts "
        "and sits behind the `MBOS_QA_IMPL` seam. **A green run here proves the invariants and the tests. It does "
        "not prove the other lanes' code.** The real spine is tested separately by the implementation-neutral spec suite: "
        "[SPINE_ACCEPTANCE.md](SPINE_ACCEPTANCE.md) (`python -m mbos_qa spine`).",
        "",
        f"- Contracts: v{pin['contracts_version']} pinned byte-exact from `{pin['source_branch']}` @ "
        f"`{pin['source_commit'][:7]}` ({len(pin['files'])} files)" + (f"; drift check vs `{drift_ref}`" if drift_ref else ""),
        f"- Contract validation: **{'PASS' if contract_rep.passed else 'FAIL'}** "
        f"({sum(c.passed for c in contract_rep.checks)}/{len(contract_rep.checks)} checks)",
        f"- Acceptance tests: **{'PASS' if test_rc == 0 else 'FAIL'}** "
        f"({sum(r[2] == 'passed' for r in rows)} passed, {sum(r[2] == 'FAILED' for r in rows)} failed, "
        f"{sum(r[2].startswith('xfail') for r in rows)} strict-xfail known gaps)",
        f"- End-to-end dry-run (flip + service): **{'PASS' if e2e_ok else 'FAIL'}** → [E2E_REPORT.md](e2e/E2E_REPORT.md)",
        "- Cross-lane ADR-0010 interop against the peers' real code: [INTEROP_REPORT.md](INTEROP_REPORT.md) "
        "(`python -m mbos_qa interop`). Open rows map to F-13, F-14 and F-15.",
        "- Each lane's own test suite, run independently: [BUILD_VERIFICATION.md](BUILD_VERIFICATION.md) "
        "(`python -m mbos_qa builds`).",
        "",
        "## Summary by acceptance test",
        "",
        "| Test | Result | Cases | Verified against |",
        "|---|---|---:|---|",
    ]
    against = {"test_a02": "mock store (SQLite triggers); Postgres role check pending F-8",
               "test_a08": "in-process LLM cap mock; LiteLLM pending F-7",
               "test_a09": "file-backed PANIC mock; egress/OpenBao pending F-7"}
    for prefix, title in GROUPS.items():
        g = [r for r in rows if r[0].startswith(prefix)]
        failed = [r for r in g if r[2] == "FAILED"]
        xf = [r for r in g if r[2].startswith("xfail")]
        res = "FAIL" if failed else ("PASS" + (f" ({len(xf)} known gap)" if xf else "")) if g else "NOT RUN"
        lines.append(f"| {title} | **{res}** | {len(g)} | {against.get(prefix, 'reference mocks (contract-conformant)')} |")
    lines += ["", "## Contract validation runner", "", "| Check | Result |", "|---|---|"]
    lines += [f"| {c.name} | {'PASS' if c.passed else 'FAIL ' + c.detail} |" for c in contract_rep.checks]
    lines += ["", "## Contract gap probes (the schema ACCEPTS these; ADR prose forbids them)", "",
              "| Probe | Status |", "|---|---|"]
    lines += [f"| {g.name} | {g.detail} |" for g in gaps]
    lines += ["", "## Findings for other lanes", "",
              "Status is as verified at the latest pins (`qa/impl_lane_pins.json`); FIXED means a test that failed now passes.", "",
              "| ID | Status | Tag | For | Finding | Recommendation |", "|---|---|---|---|---|---|"]
    lines += [f"| {i} | **{FINDING_STATUS.get(i, 'see text')}** | {tag} | {who} | {f} | {rec} |" for i, tag, who, f, rec in FINDINGS]
    lines += ["", "## Every test case", "", "| Module | Test | Outcome |", "|---|---|---|"]
    lines += [f"| {m} | `{n}` | {o} |" for m, n, o, _ in rows]
    lines += ["", "## How to reproduce", "", "```bash",
              "cd qa && python3.12 -m venv ../.venv && ../.venv/bin/pip install -r requirements.txt",
              "../.venv/bin/python -m mbos_qa run --drift-ref origin/research/agent-01-coordinator",
              "# against real lanes later:  MBOS_QA_IMPL=mbos.qa_adapter:build ../.venv/bin/python -m mbos_qa run",
              "```", ""]
    (OUT / "ACCEPTANCE_REPORT.md").write_text("\n".join(lines))
    print(f"wrote {OUT / 'ACCEPTANCE_REPORT.md'}")


def cmd_pin(ref: str):
    src = "docs/research/contracts/"
    files = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref, src], capture_output=True, text=True,
                           check=True, cwd=REPO).stdout.split()
    manifest = {}
    for f in files:
        if f.endswith("validate_contracts.py"):  # coordinator's own validator; the QA runner replaces it
            continue
        blob = subprocess.run(["git", "show", f"{ref}:{f}"], capture_output=True, check=True, cwd=REPO).stdout
        rel = f[len(src):]
        (CONTRACTS_DIR / rel).parent.mkdir(parents=True, exist_ok=True)
        (CONTRACTS_DIR / rel).write_bytes(blob)
        manifest[rel] = "sha256:" + hashlib.sha256(blob).hexdigest()
    commit = subprocess.run(["git", "rev-parse", ref], capture_output=True, text=True, check=True, cwd=REPO).stdout.strip()
    pin = json.loads((CONTRACTS_DIR / "PIN.json").read_text())
    pin.update(source_commit=commit, files=dict(sorted(manifest.items())))
    (CONTRACTS_DIR / "PIN.json").write_text(json.dumps(pin, indent=2))
    print(f"pinned {len(manifest)} files @ {commit}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mbos_qa")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("contracts", "run"):
        p = sub.add_parser(name)
        p.add_argument("--drift-ref")
    sub.add_parser("e2e")
    sub.add_parser("interop")
    sub.add_parser("card")
    sub.add_parser("install-pins")
    sp = sub.add_parser("spine")
    sp.add_argument("--rc", action="store_true",
                    help="release-candidate stack: state_backend=lane_d + gateway_mode=lane_e → docs/qa/RELEASE_CANDIDATE.md")
    p = sub.add_parser("builds")
    p.add_argument("--workdir", required=True, help="scratch dir for archives + venvs (not committed)")
    p.add_argument("--lanes", nargs="*")
    p = sub.add_parser("pin")
    p.add_argument("--ref", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "contracts":
        return 0 if cmd_contracts(a.drift_ref).passed else 1
    if a.cmd == "e2e":
        _, ok = cmd_e2e(OUT / "e2e")
        return 0 if ok else 1
    if a.cmd == "interop":
        from . import interop
        rep = interop.run()
        (OUT / "INTEROP_REPORT.md").write_text(interop.render(rep))
        for c in rep.checks:
            print(f"{c.status:7} {c.group} · {c.name} — {c.detail[:140]}")
        return 0
    if a.cmd == "install-pins":
        from . import pincheck

        print("installed:", ", ".join(pincheck.install_pins()))
        bad = pincheck.check()
        print("byte-identical to the pins" if not bad else "MISMATCH: " + "; ".join(bad[:5]))
        return 1 if bad else 0
    if a.cmd == "card":
        return cmd_card()
    if a.cmd == "spine":
        return cmd_spine(release=a.rc)
    if a.cmd == "builds":
        from . import buildverify
        py = shutil.which("python3.12") or sys.executable
        ver = subprocess.run([py, "--version"], capture_output=True, text=True).stdout.strip()
        res = buildverify.run(pathlib.Path(a.workdir), a.lanes, py)
        buildverify.save(res, OUT, ver)
        for r in res:
            print(r["lane"], r["status"], {k: r.get(k) for k in ("tests", "passed", "failures", "errors", "claim_check", "detail")})
        return 0 if all(r["status"] == "PASS" for r in res) else 1
    if a.cmd == "pin":
        cmd_pin(a.ref)
        return 0
    rep = cmd_contracts(a.drift_ref)
    gaps = run_gap_probes()
    _, e2e_ok = cmd_e2e(OUT / "e2e")
    rc, rows = cmd_tests()
    write_acceptance_report(rep, gaps, rc, rows, e2e_ok, a.drift_ref)
    return 0 if (rep.passed and rc == 0 and e2e_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
