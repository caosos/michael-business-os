# Action Gateway: wave one implementation guide

**Owner:** Agent 05 · **Status:** implemented, wave one · **Date:** 2026-10-07
**Code:** `src/mbos_governance/` · **Policy data:** `policy/` · **Tests:** `tests/` (371 passing, on PostgreSQL 16)

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
from mbos_governance import ActionGateway, PgGovernanceStore, PgPanicStore, PolicyStore

# One login per role (privileges checked by Postgres), or one DSN for all (e.g. mbos_dbos).
store = PgGovernanceStore({"agent_write": DSN_STATE_MCP, "gateway": DSN_GATEWAY,
                           "approver": DSN_OPERATOR_UI, "policy_admin": DSN_POLICY})
gw = ActionGateway(store, PolicyStore("policy/policy.v1.json"), PgPanicStore(DSN_GATEWAY),
                   panic_hooks=[DbosCancelHook(DBOS), EgressPolicyHook(...), LiteLLMBudgetHook(...)])

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
# A fresh database is FROZEN (lane D 0007 bootstrap). Connection: --dsn / MBOS_GOV_DSN / MBOS_GOV_DSN_<ROLE>.
mbos-gov panic release --level L3 --actor michael --reason "go live (dry-run)"
mbos-gov panic freeze                        # L3 global; anyone on the host may freeze
mbos-gov panic freeze --level L2 --target 'money.*'      # or category:sms
mbos-gov panic freeze --level L1 --target agent-07-marketing
mbos-gov ledger verify                      # hash-chain check
mbos-gov policy check
```

- **Where the state lives (E-02, ruling R5):** lane D's sealed, append-only `mbos.panic_state`. It is written only by `mbos.panic_set`, together with its `KILL_SWITCH_CHANGED` receipt in the same transaction, and read through `PgPanicStore` (`mbos.panic_read`). The wave-one JSON file is gone. There is one source of truth, and it is backed up and receipted.
- **When the database is unreachable:** a freeze cannot be written, but PANIC also cannot be **read**, and every reader treats that as FROZEN. The attempt is journaled locally.
- **Role enforcement by the database:**
  - engage: `gateway`, `approver` or `policy_admin`
  - release: `approver` only
  - agents (`agent_write`): no PANIC rights at all

  Tests check this with real logins.
- **Fail-closed rule:** a missing, corrupt, schema-invalid, unknown-state or checksum-mismatched file reads as FROZEN. No mutation can "repair" an unreadable file into RUNNING.
- **Who can release:** only a policy approver (`michael`), with a reason, and only while the policy is readable. A release stands only if its `KILL_SWITCH_CHANGED` receipt commits. If the receipt fails, the state is re-frozen.
- **What L3 does in wave one (FACT):** the gateway refuses every execution and every new proposal. Approved requests that have not started become `cancelled_by_freeze`, their reservations are released, and receipts are written. If an effector call is already in flight, the late PANIC read stops it before the effector runs.
- **L3/L1 side-effect hooks (E-03, `hooks.py`, all dry with no network):**
  - **`DbosCancelHook(DBOS)`.** On L3 engage it runs `DBOS.cancel_workflows` on `ENQUEUED`/`DELAYED` workflows. `PENDING` (already running) workflows are reported as `in_flight_at_freeze`, and the gateway's late PANIC read stops them. FACT: tested against real `dbos` 3.2.0 (Agent 01's pin) (local SQLite system DB, DBOS's own): 3 queued workflows cancelled, 1 running workflow finished.
  - **`EgressPolicyHook(path)`.** It writes a sealed `mbos.egress/1` file with `default: deny`. The per-agent allow-lists come from `policy.egress.allow`, which the wave-one schema pins to empty. L3, an unreadable PANIC state or an unreadable policy produces `deny_all: true`. L1 removes that agent's list. A proxy reading this file must treat a missing file or a bad checksum as deny-all.
  - **`LiteLLMBudgetHook(path)`.** It writes `mbos.litellm.keys/1`: one key spec per agent (`key_alias mbos-<agent>`, `max_budget` from `llm_spend`, `budget_duration 1d`). L3 or an unreadable state sets every budget to 0. L1 sets that agent's budget to 0. *Applying* the spec to a LiteLLM proxy is an operator step, and this code never calls it. INFERENCE: the field names follow the LiteLLM key API; re-check them once a LiteLLM version is pinned.
  - **When hooks run.** Engage hooks run right after the freeze is durable, and their results go into the `KILL_SWITCH_CHANGED` receipt. A failing hook never blocks the freeze. Release hooks run **only after** the release receipt commits, and their results go into a follow-up receipt. A rolled-back release leaves egress and budgets frozen.
  - **Generators.** `mbos-gov render egress|litellm [--out]`.
- **Still not done:** OpenBao lease revocation (no OpenBao yet), the actual proxy and LiteLLM processes, and B29 against a live proxy.

## 5. Policy as data

**Production source (E-06): lane D's `mbos.policy` / `policy_current`.**
- `mbos-gov policy publish --actor michael` (role `policy_admin`) validates `policy/policy.v1.json` and `content_rules.v1.json`, then publishes the changed keys in **one** transaction through `mbos.publish_policy`. Each published key gets a `CONFIG_VERSION_BUMPED` receipt.
  - `governance:policy/1` holds the full document. `governance:content_rules/1` holds the content rules.
  - Each category and capability gets its own row, so lane D's own constraints apply. For example, money can never be `allow`.
- **Reads fail closed.** `PgPolicyStore` reads the document and validates it against the schema **pinned in the installed code**, and the per-key rows must agree with the document. The policy is unavailable, and the gateway denies everything, if:
  - no policy has been published
  - the database errors
  - the document is tampered with or loosened
  - a per-key row has drifted from the document
- **`spine_adapter.build(dsns)`** defaults to the database policy.
- **The file below** stays the reviewed source in git, and dev/test runs can use it directly.


`policy/policy.v1.json` (`version 2026.10.07-w1`) holds the 11-category × tier × threshold matrix, the capability → category → effector map, the agent grants, quiet hours, live and shadow budgets, the money velocity cap, and the LLM-spend caps (which LiteLLM will enforce). `policy/policy.schema.json` validates the file and pins the wave-one invariants. The PDP re-reads the file whenever it changes, and every decision records `policy_version = <version>+<content hash>`. If a reload fails, the PDP refuses. It never falls back to a stale policy.

These defaults wait on Michael's decisions (`MICHAEL_DECISIONS.md`):
- dry-run shadow caps: money $1,500 per action and per day (Agent 03 REC), comms $5/day, publishing $50/day
- money velocity: 3 per hour
- quiet hours: 20:00–08:00 America/Chicago

### 5a. Recommendation actions (E-12: Deal Sniffer CONTACT / OFFER / COUNTER / BUY)

| Card action | Capability | Category | Tier | Step-up |
|---|---|---|---|---|
| CONTACT | `comms.email.send`, `comms.sms.send`, … | email / sms / … | 0 | no (unless irreversible or tainted) |
| OFFER | `offer.<email\|sms\|message>.send`, `offer.submit` | offer | 0 | **yes** |
| COUNTER | `offer.<email\|sms\|message>.counter` | offer | 0 | **yes** |
| BUY | `purchase.create` | purchase | 0 | **yes** |

- **Default deny:** an unknown capability, an ungranted agent or a category mismatch is denied. The grants are data, and agent 06 and agent 01 propose offers.
- **A binding offer can never be created under `comms.*`:**
  - Policy cross-checks make the whole policy unavailable if any `offer.*` or `purchase.*` capability maps to the wrong category, or any `comms.*` capability maps to a binding or money category.
  - The PDP also denies a `comms.*` request whose payload carries a binding key (`offer`, `counter_offer`, `offer_amount`, …; a data list) with `BINDING_UNDER_COMMS`.
- **`step_up_required(ar, policy)`** is the one rule behind the card's `requires_step_up`. The PDP result carries it (`PolicyDecision.step_up`), and the spine adapter appends `step_up=required` to the reason.
- **Cash at risk (MICHAEL_DECISIONS #1, UNDECIDED, conservative defaults as data):** `max_per_flip_usd 1500` and `max_total_active_usd 3000`.
  - Outstanding offer and purchase reservations (reserved minus released) are summed under the budget lock.
  - The refusals are `CASH_AT_RISK_PER_FLIP:<item>` and `CASH_AT_RISK_TOTAL`.
  - The limits apply to dry-run reservations. Live spend stays pinned at 0.
- **R20:** an approved request that the gateway refuses because of a freeze (L1, L2 or L3) becomes `cancelled_by_freeze`.
  - Its reservation is released and it gets an `ACTION_FAILED` receipt.
  - Releasing the freeze later does **not** revive the approval, so Michael re-approves a new proposal.
  - Pending requests are untouched, and so are approvals refused for non-freeze reasons.

## 6. Hashing: ADR-0010 (normative), supersedes R3

- **`payload_hash`** is MBOS-CJSON-1: RFC 8785 JCS with an I-JSON profile.
  - Floats are allowed, and `850.0` and `850` hash the same.
  - Rejected: NaN/±Inf, integral values beyond ±(2^53−1), non-BMP member names, U+0000 and lone surrogates.
  - A rejected payload is refused at `propose()` with `GatewayRefused("PAYLOAD_NOT_HASHABLE")`.
- **Stand-in receipt `row_hash`** is MBOS-RH-1: `sha256(CJSON(D))`.
  - D is the receipt minus `row_hash`, including `seq` and `prev_hash`.
  - Top-level nulls are dropped, except `prev_hash`.
  - There is no `|| prev_hash` concatenation.
  - The receipt `ts` is `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
- **Where the algorithm lives:** `src/mbos_governance/ids.py` contains Agent 01's reference `mbos_canonical` block **verbatim** (@`99e9ec0`). It is inlined because `tools/interop_check.py` loads `ids.py` standalone.
- **FACT:** interop row 05 = 10/10 CONFORMS @ `df826c3`. All 10 vectors, all 6 rejections and the `receipt_chain` pass, from `tests/data/vectors.json` (pinned sha256).
- **Side effect:** the PANIC-file checksum and the policy digest also use CJSON now. A state file sealed before this change reads as FROZEN, which fails closed. `mutate()` rebuilds it as FROZEN, and Michael then releases it.

## 7. Security boundary: what is real and what is not

- **FACT (tested):** inside this code base an effector cannot run without an HMAC guard token, which is minted only after all 8 checks pass. A forged token is refused, and so is a valid token with `dry_run=false`.
- **INFERENCE:** inside one Python process this stops *accidental* bypass, not a determined attacker in the same process. The real boundary is structural (ADR-0005):
  - effector credentials exist only in the gateway process
  - agents run as separate Unix users or roles with no effector secrets
  - agents get default-deny egress
  - `record_approval` is exposed only to the authenticated Operator UI, never to agent processes

  Wave one has no live credentials anywhere, so nothing exists to steal yet.
- **Storage (E-02):** `PgGovernanceStore` writes only through lane D's `mbos.*` API (`agent-04` 0007), and there is no SQLite on the production path.
  - Lane D owns the ledger (R2): MBOS-RH-1 chain, insert-only, and a receipt required for every state change.
  - The gateway owns the action-status edges and their receipts (R4).
  - Lane D re-checks G1–G3 at the `approved→executing` edge (defense in depth). Execution claims are `mbos.effector_calls` (`effector_claim`/`effector_finish`).
  - Budgets use `mbos.budget_reserve_caps` (bucket per-action/daily/global caps under one lock). The money **action-count** velocity is checked by the gateway under the same lock, because lane D's `velocity_per_hour` caps dollars.

## 8. Next (1-week path, ADR-0005 §7)

1. ~~Postgres store on Agent 04's DDL~~ **DONE (E-02).**
2. L3 hooks: egress proxy deny-all, OpenBao lease revoke, LiteLLM per-agent budget 0, DBOS `cancel` for unstarted workflows. Plus B29.
3. Sandbox policy (gVisor or E2B) and an egress allow-list for each adapter and effector.
4. Governance alerts on FREEZE, budget breach, INJECTION_SUSPECTED and stuck `executing` claims.
5. ~~A reconciliation job for stuck claims~~ **DONE (E-05):** `gw.reconcile()` / `mbos-gov reconcile` — provider lookup by idempotency key, never re-send. Agent 01 schedules it (A-03).
6. Output-side secret scan for outbound content (§17 #25–26), and the `INJECTION_SUSPECTED` tripwire (#24) wired to L2 auto-demotion.

- **R22 / F-25 (durable provider).** The simulated dry-run provider records each delivery in lane D's `mbos.effector_calls` at send time (`DurableProviderLedger`) and answers lookups from that row.
  - Crash after the send: the request settles `executed`, via the DBOS re-run of `gateway_step` or `reconcile()`, and the effector is not called again.
  - Crash before the send, or a provider that cannot prove a send: the request settles `failed` with a RECONCILED receipt. It is never re-sent, and Michael re-approves.
