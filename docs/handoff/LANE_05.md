# Lane 05 handoff (Governance / Action Gateway / PANIC)

- **Branch / head (pushed):** `research/agent-05-governance`. The head is `git log -1 origin/research/agent-05-governance`. A fresh worker starts from that, not from any chat.
- **Role and boundaries.**
  - **Owns:** the Action Gateway (the only path to any effector), the PDP (policy decisions), the 8-check execution guard, PANIC (L1 agent / L2 capability / L3 global), budget and cash-at-risk caps, the secret scan and injection tripwire, reconciliation of crashed executions, the governance alerts, the campaign, trust, jurisdiction and sandbox/egress policy data, and the adapter that plugs it into Agent 01's spine.
  - **Never touches:** the ledger DDL (lane D / Agent 04), the spine and workflows (Agent 01), other agents' branches or worktrees, CAOSCare. Nothing here may make an external effect: everything is DRY-RUN, and the policy schema pins live spend to 0.
- **Completed:** E-01..E-19 (see `docs/status/AGENT_STATUS.md` for each commit), B-04 lane-E half, X-03. Receipts are in `docs/receipts/2026-10-07-*`.
- **Outstanding:** E-20 (real jurisdiction packs), E-21 (license-gate wiring into the offer path), E-22..E-24 (pin LiteLLM fields, confirm egress hostnames, run the sandbox spec for real), and Agent 01's A-18 wiring. Each has an acceptance condition in AGENT_STATUS under "Proposed tasks".
- **Blockers:** E-20 needs Michael's `licenses_held` and cited rules. E-21 needs E-20. E-24 needs gVisor and Podman installed on the host (Michael's decision). None blocks the dry-run MVP.

## Key files and entry points
| What | Where |
|---|---|
| Gateway: propose, record_approval, execute (G1–G8), reconcile, engage/release PANIC | `src/mbos_governance/gateway.py` |
| Storage on lane D's `mbos.*` API (no SQL of our own except reads) | `src/mbos_governance/store_pg.py` |
| PDP over policy data; step_up rule; binding-key rule | `src/mbos_governance/policy.py` |
| DB-backed policy (publish / PgPolicyStore) | `src/mbos_governance/policy_pg.py` |
| Spine adapter: build, Gateway / KillSwitch / PDP over `mbos.interfaces`, engage/release, schedule_reconcile, proposer_for, campaign_decision, binding_key_violations | `src/mbos_governance/spine_adapter.py` |
| Hashing (inlined ADR-0010 reference, standalone) | `src/mbos_governance/ids.py` |
| Hooks: DBOS cancel, egress file, LiteLLM budgets | `src/mbos_governance/hooks.py` |
| Content guard, egress catalog, sandbox, alerts, campaigns, trust, jurisdiction | `content_guard.py`, `egress.py`, `sandbox.py`, `alerts.py`, `campaigns.py`, `trust.py`, `jurisdiction.py` |
| Policy and rule data, all pinned by schema | `policy/policy.v1.json` + `policy.schema.json`, `content_rules.v1.json`, `sandbox.v1.json`, `trust/`, `jurisdiction/` |
| CLI | `mbos-gov` (`src/mbos_governance/cli.py`) |
| Guides | `docs/governance/ACTION_GATEWAY.md` (main), `SANDBOX.md`, `RESERVED_PAYLOAD_KEYS.md`; `docs/integration/05-*.md` |

## Run commands
```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[test]'    # jsonschema, psycopg, pgserver (PostgreSQL 16, no root), sqlalchemy, dbos
.venv/bin/python tools/check_no_bypass.py src                       # expect: no-bypass check: PASS
.venv/bin/python -m pytest -q -p no:cacheprovider                   # the one command that proves the lane is healthy
```
- **Expected result:** 598 passed, in roughly 3 minutes. It starts its own PostgreSQL 16 cluster on port 55505 and builds lane D's schema from the vendored copy.
- **The full run takes longer than a default tool timeout:** run it in the background and wait for the result.
- **Run ONE pytest session at a time.** Two sessions fight over port 55505.
- **Quick checks:** `mbos-gov policy check`, `mbos-gov trust check`, `mbos-gov jurisdiction check`, `mbos-gov sandbox check --host` (the last reports that this host has no runsc/podman/docker/e2b).

## Interfaces with other lanes
| Lane | Consumes | Provides |
|---|---|---|
| 04 (state) | `mbos.*` API: `propose_action`, `set_action_status`, `record_approval`, `append_receipt`, `effector_claim/finish`, `budget_reserve_caps`, `panic_set/panic_read`, `publish_policy`, `verify_chain` | needs from 05: nothing; 05 only calls the API |
| 01 (spine) | `mbos.interfaces` types (vendored for tests only) | `spine_adapter.build(...)` → `.gateway`, `.kill_switch`, `.pdp`; `engage_panic`/`release_panic`; `schedule_reconcile`; `proposer_for(lane)`; `campaign_decision` |
| 02 (discovery) | `freeze-request.schema.json` | applies freeze requests as L2 PANIC (`apply_side_channel`; release is human-only); `PgPanicStore.read().blocks(...)` for its honour check |
| 06 / 07 | drafts as ActionRequests | `binding_key_violations`, proposer grants, `lane` tag convention |

**Vendored copies and how to re-vendor** (all byte-identical `git show <sha>:<path>`, sha-pinned by a test):
- `tests/vendor/agent04_state/` = lane D schema + migrator at `agent-04-state @ a08dd9f` (migrations 0000–0014). To refresh: copy `state/{mbos_state/__init__,migrate}.py`, `bootstrap/roles.sql` and `migrations/*.sql` from the new sha, regenerate `MANIFEST.sha256`, and add any new superuser bootstrap step to `tests/conftest.py` (0010 needed the pgvector extension in schema `mbos_ext`).
- `src/mbos_governance/schemas/`: frozen contracts v1.0.0 (`@1269405`), `freeze-request` (`@029356c`), `campaign` (`@c18cabc`), and the policy schema (must equal `policy/policy.schema.json`; check with `cmp`).
- `tests/vendor/agent01_mbos/mbos/interfaces.py` at `agent-01 @ 8c3e4fd`. `tests/data/vectors.json` at `99e9ec0`. `ids.py` inlines the reference `mbos_canonical` block verbatim.

## Known pitfalls
- **Commit identity:** the shared `.git/config` identity is unreliable. Use `git -c user.name='Agent 05 Governance' -c user.email='michaelos+agent-05-governance@users.noreply.github.com' commit`. The 59 earlier commits are mislabelled "Agent 07 Marketing". The correction of record is `docs/receipts/2026-10-07-provenance-correction-lane-05-authorship.md`.
- **GitHub push protection** blocks secret-shaped literals, even public example keys. Build test secrets by concatenation. If a push is rejected, rebuild only the unpushed commits.
- **Policy edits:** `policy/policy.schema.json` and `src/mbos_governance/schemas/policy.schema.json` must stay identical. Loosening a wave-one rule is a schema change reviewed by 05 and 01; editing the data alone makes the policy unavailable (deny all). The policy file hot-reloads by mtime; `mbos-gov policy publish` makes it the running policy in Postgres.
- **Test policy copy:** `tests/conftest.py` adds the three money capabilities to agent-01 in its COPY so the 11-category mechanics tests can run. The shipped policy grants them to nobody (asserted in `test_e15_*`).
- **JSON Schema quirk in the frozen ActionRequest contract:** `tier` must be 0 whenever `untrusted_inputs_present` is absent (an `if` over an absent property passes vacuously). Do not rely on tier 1.
- **MB006 refusals** need a savepoint (`cur.connection.transaction()`) or they abort the guard transaction.
- **DBOS 3.x has no `@DBOS.scheduled`:** schedules are created with `DBOS.create_schedule` after `DBOS.launch()`. `WorkflowSchedule` is a dict.
- **Lane D checks `dry_run=true` on every stored effector response:** an effector's live claim is kept under `details.effector_reported`.
- **`/run/user/1001` is a small shared tmpfs and fills up** with leftover clusters from other lanes. The harness falls back to `/tmp`.
- **Status changes are reason-specific:** only specific expiry, hash, grant or approval-defect reasons change a request's status. Transient reasons (quiet hours, budget, unreadable policy) keep the approval.

## Open questions (UNKNOWN, with who can answer)
- Michael: `licenses_held`; real cash-at-risk and dollar caps (MICHAEL_DECISIONS #1); install gVisor and Podman; payment provider choice and legal review.
- Agent 02: the egress hostnames in the catalog are my inference from provider documentation.
- Whoever pins LiteLLM: the key-API field names in the budget generator are INFERENCE.
- Agent 01: the frozen example `action-request-email-held` must be regenerated (ADR-0009), since it now violates BINDING_UNDER_COMMS.
