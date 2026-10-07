# Agent Status

Agent: 05
Role: Governance / Action Gateway / PANIC — "controlled autonomy"
Branch: research/agent-05-governance
Worktree: /home/michaelos/business-os-worktrees/agent-05-governance
State: WORKING
Done: E-10 @ ebae275 (spine_adapter: Gateway/KillSwitch/PDP over 01's mbos.interfaces on lane D; reconcile(); R4 contract docs/integration/05-spine-adapter-R4-contract.md)
Done: E-06 @ e957680 (policy publish -> mbos.policy, receipted; PgPolicyStore reads policy_current, pinned schema, row-drift/tamper => fail closed; same decisions as file)
Done: E-09 @ <E09> (alerts.collect read-only over lane D: freeze/unreadable/stuck/chain/A7/budget/injection/dry-run/reconciled; ntfy-ready JSON, never sent; CLI exit 2 on critical)
Claimed: E-07 (egress allow-list per adapter/effector as policy data + checker)
Done: B-04 lane-E half @ d3b9948 (02's fixture applies + blocks exactly that source; auto-apply decided, release human-only)
Done: E-04 @ 4fadbe7 (secret scan refuses + never stores; injection tripwire => tier 0, needs_review, step-up; 205 tests)
Done: E-02 @ 1c554cb (gateway + PANIC on lane D Postgres via mbos.* API; no SQLite in prod path; R4 role-enforced; 211 tests on PG16)
Done: E-05 @ 9391c16 (reconcile: provider lookup by idempotency key; found→executed, not found→failed, no answer→NEEDS_HUMAN; never re-sends; exactly once)
Done: E-01 @ df826c3 (interop row 05 = 10/10; vectors receipt_chain verifies; 141 tests)
Done: E-03 @ e12caa3 (L3 DBOS cancel verified on real dbos 3.2.0; deny-all egress + LiteLLM budget generators; 157 tests)
Current phase: ROUND TWO — wave two (foreman loop, docs/COORDINATION.md)
Started: 2026-10-06
Last updated: 2026-10-07 (E-09 done; claimed E-07)

## Current objective
**SUPERSEDED by ADR-0010 (E-01):** Agent 01 binding rulings for lane E
(`origin/research/agent-01-coordinator@bed7609:docs/integration/ROUND_TWO_INTEGRATION.md`):
- R7: propose-only grant `comms.email.send` / `comms.sms.send` for `agent-01-coordinator`.
- R3: align payload_hash with the normative canonical JSON (drop the float refusal).
  Result (FACT, 121 tests pass): grants added, policy version `2026.10.07-w1.1` (with an explicit
  `grant_semantics`: grants = propose-only, the gateway alone executes). The float refusal was dropped.
  Hashes are byte-identical with 01 `mbos.hashing` and 06 `operator_ui.util` (golden vectors
  pinned in tests). NaN/Infinity/non-JSON payloads are refused at `propose()` (fixed a bug where a
  rejected NaN proposal crashed on storage).
NOTE: at first check (2026-10-07 ~12:00) no READY_QUEUE existed; Agent 01 published it at 99e9ec0.
ADR-0010 replaces R3's json.dumps form with MBOS-CJSON-1 (RFC 8785; 850.0 == 850), so the R3
hashing in 5b36a09 is superseded by E-01. The R7 grant stands.

Previous objective:
Wave one: Action Gateway + fail-closed governance layer per ADR-0004/ADR-0005 against frozen
contracts v1.0.0. **Delivered.**

## Completed (round two, wave one)
FACT — 114 tests pass (`docs/receipts/2026-10-07-round-two-gateway-build.md`).
Package `src/mbos_governance/` (Python 3.12, only dependency `jsonschema`):
- **ActionRequest validation** — frozen contract + payload_hash recomputation, caller ==
  proposed_by, initial status `drafted`, on_behalf_of michael, created/expiry sanity, lifetime
  cap, provenance must exist ("no action without provenance"), derived_from must exist.
- **Policy decision interface** — `decide(action_request) → {allow|deny|require_approval,
  tier, policy_decision_ref}`; pure non-LLM code over **policy data** (`policy/policy.v1.json`
  + `policy.schema.json`), hot-reloaded, never serves a stale policy.
- **Approval validation** — YES/NO/MODIFY/HOLD semantics, approvers, channels, scope=once,
  step-up, auth context; latest decision wins; invalid YES is recorded but not executable.
- **payload_hash equality** — recomputed = stored = `payload_hash_seen`; floats refused.
- **Approval expiry** — approval expires_at, 24h policy TTL cap, ActionRequest expires_at.
- **Idempotency enforcement** — duplicate proposals collapse; execution claim UNIQUE per key;
  second delivery returns stored result; crashed in-flight claim is never blind-retried.
- **Budget guard** — reserve → commit/release; per-action / daily-bucket / global-daily /
  money-velocity caps; live caps pinned 0; dry-run shadow caps enforced; 100 parallel
  approvals never overshoot (FACT).
- **Capability guard** — least-privilege `agent_grants` data; re-checked at execution on the
  current policy.
- **PANIC L1/L2/L3** — checksum-sealed atomic state file outside the DB; missing/corrupt/
  tampered = FROZEN; L3 cancels queued requests; late PANIC read just before the effector;
  release only by Michael and rolled back if its receipt fails; CLI `mbos-gov`.
- **Dry-run guard** — `system_mode` can only be round_one|mvp; only effector is
  `DryRunEffector`; an effector reporting `dry_run≠true` trips L3 PANIC.
- **Fail closed** — unreadable policy or PANIC state ⇒ all 8 checks fail, proposals rejected.
- **8 guard checks** (ADR-0005) in one transaction, all failures reported with codes.
- **Receipts** — every transition, same transaction, validated against receipt.schema.json,
  provenance must exist, hash-chained, insert-only; `verify_chain` detects tampering.
- **No bypass** — effectors require a gateway-minted HMAC guard token;
  `tools/check_no_bypass.py` lints for network/messaging/payment imports outside effectors.
- Docs: `docs/governance/ACTION_GATEWAY.md` (integration guide, guard table, PANIC runbook),
  ADR-05-003, build receipt.

## Findings
- FACT: contract v1.0.0 does not define `payload_hash` canonicalization; the frozen example
  `action-request-email-held` has a payload_hash not reproducible from its payload, so the
  gateway would reject it (`PAYLOAD_HASH_MISMATCH`). → ADR-05-003 R1.
- FACT: receipt `type` enum lacks a guard-refused / expired event; wave one maps onto
  `ACTION_FAILED` / `POLICY_DECIDED`. → ADR-05-003 R2.
- INFERENCE: the in-process guard token stops accidental bypass only; real isolation needs
  process/Unix-user separation + default-deny egress (1-week path).

## Decisions made
- ADR-05-003 (PROPOSED): confirms merged 3-level PANIC; accepts Biscuit/SPIFFE deferral;
  policy-as-data with schema-pinned wave-one invariants; SQLite reference store behind a
  swappable seam; contract v1.1 requests R1–R3.

## Unknowns
- Recipient-local timezone for quiet hours (policy tz America/Chicago used until Agent 06's
  consent ledger supplies it).
- Agent 04's Postgres DDL for action_requests / approvals / budget_ledger / policy (store swap).
- Operator UI authentication (lane F) — `record_approval` assumes an authenticated surface.

## Blockers
None for wave one.

## Needs Michael decision
Unchanged; wave one ships conservative defaults as data (`MICHAEL_DECISIONS.md` #1, #3, #5):
dollar caps (dry-run shadow caps $1,500/deal, comms $5/day, publishing $50/day; live $0),
step-up method, no delegation.

## Needs coordinator review (Agent 01)
- ADR-05-003 requests R1 (payload canonicalization + regenerate example), R2 (receipt
  types), R3 (`pdp_` prefix).
- Integration: DBOS workflow should call `ActionGateway.execute()` inside a step; agent ids
  must be the branch names (`agent-0N-*`).
- Agent 04: `GovernanceStore` method seam for the Postgres swap.

## Files produced (round two)
- pyproject.toml, .gitignore
- src/mbos_governance/{__init__,ids,contracts,policy,panic,store,effectors,gateway,cli}.py
- src/mbos_governance/schemas/ (frozen v1.0.0 copies + PROVENANCE.md)
- policy/policy.v1.json, policy/policy.schema.json
- tools/check_no_bypass.py
- tests/{conftest,test_gateway,test_policy_and_panic,test_static}.py
- docs/governance/ACTION_GATEWAY.md
- docs/decisions/ADR-05-003-wave-one-gateway-implementation.md
- docs/receipts/2026-10-07-round-two-gateway-build.md

## Proposed tasks
- E-06 (P1) Policy data into lane D: publish policy/policy.v1.json + content_rules into mbos.policy via
  publish_policy (policy_admin), PDP reads policy_current; file stays as the signed source. Fail closed if
  no current row. (Lane-E + 04 API, no DDL change expected.)
- E-07 (P2) Egress allow-list per adapter/effector as policy data + render for the proxy (ADR-0005 §7,
  assigned to 05). Wave one stays all-empty; adds the B-03 GSA/Trash Nothing read-only hosts as
  disabled-by-default entries so lane B's enablement is a reviewed data change.
- E-08 (P2) Sandbox policy (ADR-0005 §7): which processes run under gVisor vs E2B; written spec +
  runnable config check. Host has no Podman (memory: EliteDesk facts) — doc + checker only.
- E-09 (P2) Governance alerts (ADR-0005 §7): FREEZE, budget breach (MB006 refusals), INJECTION_SUSPECTED,
  NEEDS_HUMAN reconcile, stuck claims > TTL — as a read-only query module + ntfy-ready JSON, no sends.
- (for 04) count-based velocity in budget_reserve_caps (e.g. caps.velocity_actions_per_hour): lane E's
  money cap is ACTIONS/hour; 0007's velocity_per_hour is DOLLARS/hour. Interim: gateway counts under
  mbos.budget_lock in the same txn (correct, but two places).
- (for 05/04) move PDP policy data from policy/policy.v1.json into lane D's mbos.policy/policy_current.
- B-04 (02-led, +05): lane E side is ready now. L2 PANIC already accepts the key
  `discovery.source.<src>.read` (exact) or `discovery.source.*` (prefix), and any actor —
  including `agent-02-opportunity` — may ENGAGE (only Michael releases). Proposed request shape:
  `gw.engage_panic("L2", "discovery.source.<src>.read", actor="agent-02-opportunity",
  reason="<health code>: <detail>")`. Agent 02 to confirm; I will add the shared fixture test then.
- A-03 wiring note for Agent 01: construct `ActionGateway(..., panic_hooks=[DbosCancelHook(DBOS),
  EgressPolicyHook(path, ps), LiteLLMBudgetHook(path, ps)])`.
- (E-02 prep, done as a handoff, no DDL touched) `docs/integration/05-requirements-for-04-migration-0005.md`:
  what lane E needs from 04's 0005 — panic_events table + panic_set, effector_calls claims, three
  missing status edges (approved→expired, approved→failed, executing→cancelled_by_freeze), budget
  mode/zero-amount/multi-cap. For Agent 04 (D-01) and Agent 01 to triage.

## Next action
1-week path (ACTION_GATEWAY.md §8): Postgres store on Agent 04 DDL; L3 hooks (egress
deny-all, OpenBao, LiteLLM budget→0, DBOS cancel); sandbox + egress allow-list; governance
alerts; stuck-claim reconciliation job; output secret scan + INJECTION_SUSPECTED tripwire.
