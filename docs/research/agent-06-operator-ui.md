# Agent 06: Operator UI / Approval UX (build lane F)

**Updated:** 2026-10-07 (wave two, task **F-01** = ruling R10) · **Branch:** `research/agent-06-communications`
**Spine:** Agent 01's `mbos` @ `bf215b2` (F-01 was built on `bed7609`, F-02 on `99e9ec0`), installed into this worktree's `.venv` from a `git archive` copy. Not merged.

**Dry-run only.** The UI cannot send, spend, publish or contact anyone. It records Michael's decision and nothing else. Execution happens only in the spine's DBOS item workflow, which goes through the lane E gateway to the dry-run effector.

Evidence tags: **FACT**, **INFERENCE**, **RECOMMENDATION**, **UNKNOWN**.

---

## 1. Architecture after R10

```
browser ──POST form──► server.App ──► ux (PIN step-up, HOLD presets; no side effects)
                                   └─► backend.SpineBackend.decide
                                         ├─ engine.begin(): mbos.spine.decide(..., channel="web")   ← ONE transaction:
                                         │                    approval + provenance + receipt + status
                                         └─ DBOSClient.send(item:<id>, {"kind":"decision"})          ← wake-up only
DBOS worker (`mbos worker`) ── item_lifecycle ── poll_decision ── YES → gateway → DryRunEffector → ACTED
                                               ├─ NO → REJECTED → ARCHIVED
                                               ├─ MODIFY → successor areq (needs its own YES)
                                               └─ HOLD → durable timer: renotify / hold_until / escalate / michael_ping
```

| Module | Role |
|---|---|
| `backend.py` | Read-only queries over `mbos.*` (items, action_requests, approvals, provenance, receipts via `ledger.load_receipts`, `governance_flags`, `verify_chain`). Its **one write path** is `decide()` → `spine.decide`, then a DBOS wake. `ping()` sends the `michael_ping` wake for "Wake now". |
| `ux.py` | Two things only. HOLD presets → the `hold` dict, always with a concrete `hold_until` so the spine's +24h default never overrides Michael. PIN → `auth_context.step_up`, using the spine's own `requires_step_up`. |
| `views.py` | Card and queue view-model ("why", economics, risk, provenance, lineage, receipts). Unchanged UX. |
| `server.py` | Loopback-only HTTP, Host-header check, CSRF, CSP `default-src 'none'`, HTML escaping. Unchanged. |

**Removed per R10:** `store.py` (SQLite ledger), `gateway.py` (`DryRunGateway`), `effectors.py`, `approvals.py` (including `tick()`), `seed.py`, `contracts.py` and `util.py`. A test fails if `sqlite3`, `DryRunGateway`, `def tick`, `Effector`, `append_receipt` or raw `INSERT`/`UPDATE` reappear in the package.

### Run it (dev)
```bash
cd /home/michaelos/business-os-worktrees/agent-06-communications
eval "$(.venv/bin/mbos devdb up)"                                                 # pgserver Postgres 16, exports MBOS_* URLs
.venv/bin/mbos worker --fixture tests/fixtures/illustrative.json &                # spine worker, ILLUSTRATIVE fixtures
MBOS_OPERATOR_PIN=<pin> .venv/bin/python -m operator_ui serve                     # http://127.0.0.1:8765/
.venv/bin/python -m pytest -q tests -p no:cacheprovider                           # 42 tests (16 UI on the real spine + 26 comms spec)
```
The setup for `.venv` (uv, Python 3.12, `mbos[dev]` from the pinned `99e9ec0` archive) is in the F-01 receipt.

## 2. Decision rules: who enforces what (FACT; tests in `tests/test_operator_ui.py`)

| Rule | Enforced by | Test |
|---|---|---|
| YES = frozen payload only | The form has no payload field. The spine refuses a `payload_hash_seen` mismatch. The workflow and gateway execute the stored payload; the test asserts `effector_calls.request == payload` and its hash. | `test_yes_goes_through_spine_…`, `test_stale_hash_is_refused_by_the_spine` |
| Step-up on irreversible or money-like YES | UI: the PIN must match `MBOS_OPERATOR_PIN`, and an unset PIN refuses. The spine independently refuses without `step_up=true`. | same; mutation-checked (disabling the UI check fails the test) |
| No double execution | The spine only accepts decisions while a request is pending or held. | double-submit assertion |
| NO = reason + archive | UI pre-check, then the spine and the `Approval` contract. The workflow goes REJECTED → ARCHIVED. | `test_no_requires_reason_and_archives` |
| MODIFY = new ActionRequest | `spine.decide(new_payload=…)` creates the successor (`derived_from`, new hash) in `pending_approval`. The old request becomes `rejected`. Removing fields or invalid JSON is refused. The UI redirects to the successor card, which links back to the original. | `test_modify_creates_new_request_…`, `test_modify_rejects_…` |
| HOLD = durable, never auto-executes | The approval's `hold` plus the DBOS workflow timer. "Wake now" sends `michael_ping`, which re-presents the request and never executes it. | `test_hold_preset_…_wake_now_…`, `test_hold_tomorrow_8am_and_custom_time` |
| Web safety | CSRF, Host check (403), escaping | `test_csrf_host_and_escaping` |
| Ledger view | `mbos.verify_chain()` | `test_ledger_page_uses_spine_verify_chain` |

## 3. HOLD presets → spine `hold`

| Preset | `hold_until` | `wake_on` | Re-notify |
|---|---|---|---|
| Until tomorrow 8am | next 08:00 America/Chicago | time, michael_ping | PT24H |
| 24 hours / 3 days | +24h / +72h | time, michael_ping | PT24H |
| Until new info | +72h (re-present) | new_info, price_change, auction_ending, michael_ping | PT24H |
| Custom | chosen local time | time, michael_ping | PT24H |

The spine sets `escalate_after` to its default, P7D.

FACT (`bed7609`): the workflow acts on `hold_until`, `escalate_after`, `renotify_after` and `michael_ping`. **It does not act on `new_info`, `price_change` or `auction_ending`.** Those are recorded for when lanes B and C send them. This is a proposed task (see status).

## 4. Gaps and notes
- **`notify_decision`** did not exist at `bed7609`. Agent 01 added it as A-07 (`bf215b2`), and the UI now calls `mbos.workflows.notify_decision(item_id, approval_id)` after `spine.decide`. "Wake now" still uses a `DBOSClient` ping, because `workflows.ping` needs a launched runtime. The DB row stays the source of truth.
- **R12** (`bf215b2`): a YES on a HELD item re-presents it first (HELD → AWAITING_APPROVAL → APPROVED). This is covered by `test_yes_on_a_held_request_re_presents_then_executes`.
- **The NO archive checkbox was removed.** The spine always archives after NO, so the UI no longer offers a choice it cannot honour.
- **`SpineBackend.components`** must match the worker's lanes, because `spine.decide` classifies a MODIFY successor with the PDP. The default is the reference lanes, the same as `mbos decide`. When lane E's real PDP is wired (A-03), the UI must be built with the same `Components`.
- **Step-up method** is `local_pin`. WebAuthn/TOTP and remote access remain lane E work. The UI stays loopback-only.
- The wave-one record (SQLite stand-in, 29 tests) is in git history at `3e51ba4`.

## 5. ADR-0010 conformance (task F-02)
- `operator_ui/mbos_canonical.py` is a **byte-identical** vendored copy of `docs/research/contracts/canonical/mbos_canonical.py`, at coordinator commit `99e9ec0`. A test enforces the byte identity.
- The old `util.canonical_json` (sorted keys; `850.0` → `850.0`) and the stand-in `row_hash` (`… || prev_hash`) were already deleted in F-01. **Lane 06 has no other hashing code.**
- The UI uses the reference in two read-only places:
  1. **Card:** it recomputes `sha256_of(payload)`, independent of the spine. The card shows "verified (MBOS-CJSON-1)", and **offers YES only when what Michael sees hashes to `payload_hash`.** Otherwise it shows "YES unavailable", and NO/MODIFY/HOLD remain.
  2. **Ledger page:** besides the DB's `verify_chain()`, it re-verifies the exported chain in Python with `mbos_canonical.verify_chain` (MBOS-RH-1).
- FACT: the spine's real chain at `99e9ec0` passes the independent MBOS-RH-1 check in the tests.

## 6. Operator pages (task F-09)
| Page | What it shows | Writes |
|---|---|---|
| Card → **Outcome** | Outcomes recorded for the item; once settled, a form (lane-specific kinds, realized $/hours/days, notes) | `spine.record_outcome` (receipted; feeds LEARN with predicted-vs-actual pairs) |
| `/outcomes` | Recent outcomes with net $ | none |
| `/holds` | HOLD backlog by wake time; overdue holds flagged | none |
| `/sources` | Lane B source health (`MBOS_SOURCE_HEALTH_FILE`), worst first, freeze reasons, staleness | none (clearing a freeze stays lane B's human CLI) |

Every page keeps the loopback, Host-check, CSRF and CSP guards (R14: human channel only).

## 7. Morning digest (task F-10)
`/digest` renders lane C's C-08 ranking (`mbos_economics.digest.build_digest`) **unchanged**: rank, bucket, escaped title linked to the open card, lane C's action and reason, deadline window, value $/h, and refs with `/provenance/<id>` links. Items without a lane-C engine scorecard are listed under "Not ranked" with the reason, never dropped silently. The page is read-only.

## 8. Daily summary (task F-12)
`python -m operator_ui summary --out-dir DIR [--as-of ISO]` writes `daily-summary-<date>.md` and `.html` **locally**, and the same content is on `/summary`. It is never sent. Sections: digest top-N, HOLD backlog (overdue first), yesterday's outcomes (America/Chicago calendar day) with net $, and source health. It is deterministic for a given store state and `as_of` (`summary_hash` in the header), and all untrusted text is escaped.

## 9. Lane D + lane E (task F-04)
`SpineBackend(..., lane="lane_d")` reads lane D's contract-document views and writes only through `mbos.spine_d`. `MBOS_STATE_BACKEND=lane_d python -m operator_ui serve` builds the UI with the worker's Components (`lane_e_components`: Agent 05's gateway, PDP and kill switch). Tests: `tools/run_tests.sh` (reference suite and lane D suite in separate processes).
