# Action Gateway: wave one implementation guide

**Owner:** Agent 05 · **Status:** implemented, wave one · **Date:** 2026-10-07
**Code:** `src/mbos_governance/` · **Policy data:** `policy/` · **Tests:** `tests/` (121 passing)

> Core law: no action without a receipt, and no receipt without provenance.
> Governance rule: models may PROPOSE. Non-LLM policy code AUTHORIZES.

Tags: **FACT** = verified by the test suite in this branch. **INFERENCE**, **RECOMMENDATION** and **UNKNOWN** are marked where they apply.

---

## 1. What wave one guarantees

| Rule | How it is enforced | Test |
|---|---|---|
| Every action is tier 0 | `policy.schema.json` pins `tier`/`max_tier` to `const 0`. The PDP takes the minimum of the requested and category tiers. G6 refuses `tier != 0` | `test_policy_cannot_loosen_wave_one_invariants`, `test_decide_forces_tier_zero` |
| Michael approves everything externally consequential | All 11 categories are `require_approval`, and `allow` is not a legal value in the policy schema. Only `approvers: ["michael"]` can approve | `test_every_category_blocked_without_approval[×11]` |
| Every effector is DRY-RUN | `system_mode ∈ {round_one, mvp}` (the schema has no `live`). The only registered effector is `DryRunEffector`. G8 checks this. An effector that answers `dry_run≠true` trips an **L3 PANIC** | `test_effector_claiming_live_trips_l3_panic`, `assert_ledger_sound` (A7) |
| No delegation | The schema pins `delegation_enabled: false` and `allowed_scopes: ["once"]`. A `standing_rule` approval is refused | `test_invalid_yes_is_recorded_but_not_executable[SCOPE]` |
| No real-world spend | The schema pins every `budgets.live.*` cap to `const 0`. Simulated spend goes to the `dry_run` shadow caps | `test_daily_cap_is_hard`, `test_parallel_approvals_never_overshoot` |
| No outbound calling, texting or email | No effector exists for these. `tools/check_no_bypass.py` fails CI on any network, messaging or payment import outside `effectors.py` | `test_no_bypass_in_repo` |
| Fails closed | An unreadable policy fails all 8 checks. A missing, corrupt or tampered PANIC file reads as **FROZEN** | `test_unreadable_policy_fails_closed`, `test_unreadable_panic_state_fails_closed[×3]` |

**RECOMMENDATION:** loosening any of these rules means changing `policy.schema.json`, reviewed by Agent 05 and Agent 01. Editing the data alone cannot do it.

## 2. How other lanes use it (the only path to an external effect)

```python
from mbos_governance import ActionGateway, GovernanceStore, PolicyStore, PanicStore

gw = ActionGateway(GovernanceStore("var/governance.sqlite3"),
                   PolicyStore("policy/policy.v1.json"),
                   PanicStore("var/panic_state.json"))

gw.record_provenance(prov)              # provenance.schema.json; must exist before it is cited
res = gw.propose(action_request, caller="agent-06-communications")   # agent → gateway
#   res.outcome: pending_approval | rejected | duplicate      res.reasons: [...]
gw.record_approval(approval)            # Operator UI / CLI only (Michael's YES/NO/MODIFY/HOLD)
res = gw.execute(action_request_id)     # worker → 8-check guard → DryRunEffector → receipts
#   res.outcome: executed | duplicate | refused | failed
```

- **Agents (02, 03, 06, 07, the Item workflow):** build an ActionRequest that conforms to the contract, with `status: "drafted"`, `tier: 0`, `on_behalf_of: "michael"`, `payload_hash = sha256(canonical(payload))` (see §6), and at least one recorded `provenance_id`. `proposed_by` must equal the caller's agent id.
- **Operator UI (lane F):** call `record_approval`. Set `payload_hash_seen` to the hash of the payload that was *displayed*. Set `auth_context.method` always, and `step_up: true` for money, purchase, offer, external commitment and every **irreversible** action.
- **DBOS workflow (Agent 01):** call `execute()` inside a step. An `executed` claim makes retries safe, because a repeat call returns `duplicate` with the stored result. If a claim is stuck in `executing` after a crash, the call returns `refused` with "reconciliation required". The gateway never retries blind.
- **Agent ids** are the branch names: `agent-01-coordinator` … `agent-07-marketing`. Grants are listed in `policy.v1.json → agent_grants`.

## 3. Execution guard: the 8 checks (ADR-0005 §2)

All 8 checks run in **one** `BEGIN IMMEDIATE` transaction. Every failure is reported, not only the first. The claim and the `ACTION_EXECUTING` receipt commit in that same transaction. PANIC is read once more immediately before the effector call.

| # | Check | Failure codes |
|---|---|---|
| G1 | Approval is valid. The latest decision is YES, from an approver, on an allowed channel, with scope `once`, step-up where required, an auth context, and status `approved` | `NO_APPROVAL`, `LATEST_DECISION_IS_*`, `DECIDER_NOT_APPROVER`, `CHANNEL_NOT_ALLOWED`, `SCOPE_NOT_ALLOWED`, `STEP_UP_REQUIRED`, `AUTH_CONTEXT_REQUIRED`, `STATUS_NOT_APPROVED` |
| G2 | Nothing has expired: the approval's `expires_at`, the policy TTL cap (24h), and the ActionRequest's `expires_at` | `APPROVAL_EXPIRED`, `ACTION_REQUEST_EXPIRED` → status `expired` |
| G3 | `payload_hash` equality: recomputed = stored = `payload_hash_seen` | `PAYLOAD_MUTATED_AFTER_PROPOSAL`, `APPROVAL_PAYLOAD_HASH_MISMATCH` → status `failed` |
| G4 | The idempotency key has not been claimed | `IDEMPOTENCY_KEY_ALREADY_CLAIMED`, or `duplicate` with the stored result |
| G5 | Budget is reserved. Caps checked: per action, daily per bucket, global daily, and money velocity per hour | `BUDGET_*` |
| G6 | Grant constraints. The PDP re-runs on the **current** policy, plus tier 0 and quiet hours for SMS and calls | `CAPABILITY_NOT_HELD`, `QUIET_HOURS`, `TIER_NOT_ZERO`, … |
| G7 | Kill switch is clear: L3, L1 agent, and L2 capability or category | `PANIC_*`, `PANIC_STATE_UNREADABLE` |
| G8 | Dry-run is forced. The mode is dry-run and the effector supports it | `LIVE_MODE_NOT_AVAILABLE_IN_WAVE_ONE`, `NO_EFFECTOR`, `EFFECTOR_CANNOT_DRY_RUN` |

A refusal writes `ACTION_FAILED` (`effect: none`, `effector_response.status: guard_refused`) when an approval exists, and `POLICY_DECIDED` (deny) when none does. The effector is not called.

**Receipts for one executed action:** `ACTION_PROPOSED → POLICY_DECIDED → APPROVAL_REQUESTED → APPROVAL_DECIDED → BUDGET_RESERVED → ACTION_EXECUTING → BUDGET_COMMITTED → ACTION_EXECUTED`. Each receipt is checked against `receipt.schema.json` v1.0.0. Each one cites provenance that must already exist. Each one is hash-chained.

## 4. PANIC runbook

```bash
mbos-gov panic status                       # exit 0 RUNNING, 2 FROZEN/unreadable
mbos-gov panic init --actor michael         # first boot: creates the state FROZEN
mbos-gov panic release --level L3 --actor michael --reason "go live (dry-run)"
mbos-gov panic freeze                        # L3 global; anyone on the host may freeze
mbos-gov panic freeze --level L2 --target 'money.*'      # or category:sms
mbos-gov panic freeze --level L1 --target agent-07-marketing
mbos-gov ledger verify                      # hash-chain check
mbos-gov policy check
```

- **Where the state lives:** `var/panic_state.json`, written atomically and sealed with a sha256 checksum. It is deliberately kept **out** of the database, so `freeze` still works when the database is down. In that case the event goes to `panic_state.json.journal.jsonl` for later receipting.
- **Fail-closed rule:** a missing, corrupt, schema-invalid, unknown-state or checksum-mismatched file reads as FROZEN. No mutation can "repair" an unreadable file into RUNNING.
- **Who can release:** only a policy approver (`michael`), with a reason, and only while the policy is readable. A release stands only if its `KILL_SWITCH_CHANGED` receipt commits. If the receipt fails, the state is re-frozen.
- **What L3 does in wave one (FACT):** the gateway refuses every execution and every new proposal. Approved requests that have not started become `cancelled_by_freeze`, their reservations are released, and receipts are written. If an effector call is already in flight, the late PANIC read stops it before the effector runs.
- **Not yet in wave one:** OpenBao lease revocation, egress proxy deny-all, LiteLLM budget→0, and DBOS queue cancel. None of that infrastructure exists yet. These are hooks for the 1-week path (§8).

## 5. Policy as data

`policy/policy.v1.json` (`version 2026.10.07-w1`) holds the 11-category × tier × threshold matrix, the capability → category → effector map, the agent grants, quiet hours, live and shadow budgets, the money velocity cap, and the LLM-spend caps (which LiteLLM will enforce). `policy/policy.schema.json` validates the file and pins the wave-one invariants. The PDP re-reads the file whenever it changes, and every decision records `policy_version = <version>+<content hash>`. If a reload fails, the PDP refuses. It never falls back to a stale policy.

These defaults wait on Michael's decisions (`MICHAEL_DECISIONS.md`):
- dry-run shadow caps: money $1,500 per action and per day (Agent 03 REC), comms $5/day, publishing $50/day
- money velocity: 3 per hour
- quiet hours: 20:00–08:00 America/Chicago

## 6. Payload hash canonicalization (ruling R3, normative)

`payload_hash = "sha256:" + hex(sha256(UTF-8(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))))`.

- Money values are JSON numbers, using Python's deterministic float repr (R3). This replaces wave one's "no floats" rule.
- **FACT:** this is byte-identical to Agent 01's `mbos.hashing.sha256_of` and Agent 06's `operator_ui.util.canonical_json`. Golden vectors are pinned in `test_payload_hash_matches_r3_cross_lane_vectors`.
- Payloads that are not valid JSON (NaN, Infinity, or non-JSON types) are refused at `propose()` with `GatewayRefused("PAYLOAD_NOT_HASHABLE")`. They are never hashed differently.
- **Caution (07 F-14):** `850` and `850.0` hash differently. The gateway hashes the exact stored payload, so the proposer and the Operator UI must not re-normalise numbers (for example through Decimal) between proposal and approval. If they do, G3 refuses the action, which fails closed.
- The frozen example `action-request-email-held` still does not reproduce. ADR-0009 regenerates it.

## 7. Security boundary: what is real and what is not

- **FACT (tested):** inside this code base an effector cannot run without an HMAC guard token, which is minted only after all 8 checks pass. A forged token is refused, and so is a valid token with `dry_run=false`.
- **INFERENCE:** inside one Python process this stops *accidental* bypass, not a determined attacker in the same process. The real boundary is structural (ADR-0005):
  - effector credentials exist only in the gateway process
  - agents run as separate Unix users or roles with no effector secrets
  - agents get default-deny egress
  - `record_approval` is exposed only to the authenticated Operator UI, never to agent processes

  Wave one has no live credentials anywhere, so nothing exists to steal yet.
- **Storage:** `GovernanceStore` is a SQLite reference implementation with insert-only triggers, a hash chain and same-transaction receipts. RECOMMENDATION: Agent 04's Postgres DDL replaces it behind the same methods. The gateway logic does not change.

## 8. Next (1-week path, ADR-0005 §7)

1. Postgres `GovernanceStore` on Agent 04's DDL. Roles: `gateway` writes, agents read.
2. L3 hooks: egress proxy deny-all, OpenBao lease revoke, LiteLLM per-agent budget 0, DBOS `cancel` for unstarted workflows. Plus B29.
3. Sandbox policy (gVisor or E2B) and an egress allow-list for each adapter and effector.
4. Governance alerts on FREEZE, budget breach, INJECTION_SUSPECTED and stuck `executing` claims.
5. A reconciliation job for stuck claims. Effectors that work with real providers will query the provider by idempotency key before deciding.
6. Output-side secret scan for outbound content (§17 #25–26), and the `INJECTION_SUSPECTED` tripwire (#24) wired to L2 auto-demotion.
