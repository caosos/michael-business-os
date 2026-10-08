# Agent Status

Agent: 05
Role: Governance / Action Gateway / PANIC ("controlled autonomy")
Branch: research/agent-05-governance
Worktree: /home/michaelos/business-os-worktrees/agent-05-governance
State: CLOSED
Last head: see `git log -1` on origin/research/agent-05-governance (handoff: docs/handoff/LANE_05.md)
Last updated: 2026-10-07 (lane closeout, ADR-0014; everything DRY-RUN)

## Where to start
Read `docs/handoff/LANE_05.md`. It has the commands, the interfaces and the pitfalls. This file is the ledger of what is done and what is proposed.

## Done (E-01..E-19 plus B-04 lane-E half and X-03; commit hashes are on this branch)
Done: E-01 @ df826c3 (interop row 05 = 10/10; vectors receipt_chain verifies; 141 tests)
Done: E-02 @ 1c554cb (gateway + PANIC on lane D Postgres via mbos.* API; no SQLite in prod path; R4 role-enforced; 211 tests on PG16)
Done: E-03 @ e12caa3 (L3 DBOS cancel verified on real dbos 3.2.0; deny-all egress + LiteLLM budget generators; 157 tests)
Done: E-04 @ 4fadbe7 (secret scan refuses + never stores; injection tripwire => tier 0, needs_review, step-up; 205 tests)
Done: E-05 @ 9391c16 (reconcile: provider lookup by idempotency key; found→executed, not found→failed, no answer→NEEDS_HUMAN; never re-sends; exactly once)
Done: E-06 @ e957680 (policy publish -> mbos.policy, receipted; PgPolicyStore reads policy_current, pinned schema, row-drift/tamper => fail closed; same decisions as file)
Done: E-07 @ 2d65401 (egress.catalog as policy data, all disabled in wave one; check_catalog in the fail-closed loader; effective_allow feeds render_egress)
Done: E-08 @ 0b55f52 (sandbox spec as data + I1–I8 checker; host has no runsc/podman/docker/e2b — report only)
Done: E-09 @ c68f3b2 (alerts.collect read-only over lane D: freeze/unreadable/stuck/chain/A7/budget/injection/dry-run/reconciled; ntfy-ready JSON, never sent; CLI exit 2 on critical)
Done: E-10 @ ebae275 (spine_adapter: Gateway/KillSwitch/PDP over 01's mbos.interfaces on lane D; reconcile(); R4 contract docs/integration/05-spine-adapter-R4-contract.md)
Done: E-11 @ 1c12a24 (lane D re-vendored @ a08dd9f/0014; velocity count now in mbos.budget_reserve_caps; in-Python count deleted; 305 tests)
Done: E-12 @ c507ac0 (offer.*/counter/purchase.* tier0+step-up, binding never under comms.*, cash-at-risk defaults as data, R20 cancelled_by_freeze; 338 tests)
Done: E-13 @ ecf1600 (F-24: freeze/unreadable/corrupt PANIC denial settles approved->cancelled_by_freeze, 6-mode regression; F-25/R22: durable dry-run provider in mbos.effector_calls, after-send->executed, before/unproven->failed RECONCILED; F-22: publish.* propose-only grants for 07+01; 362 tests)
Done: E-14 @ cc0128c (spine_adapter: build wires hooks; engage_panic/release_panic/panic_state; schedule_reconcile + .activate() on real DBOS 3.2; L3 never cancels the reconcile workflow; call-sequence doc)
Done: E-15 @ 4ab56f7 (F-40 backstop: approved + non-freeze, non-transient refusal => failed with ACTION_FAILED same txn, transient (quiet hours/budget/unreadable policy) keeps approval; F-41: agent-01 grants narrowed, money.payment.send/price.change/commit.external granted to nobody, proposer_for(lane); 408 tests)
Done: E-16 @ 716098e (binding keys: top-level reserved names + any-depth amount names; nested binding:false allowed; top-level offer denied; binding_key_violations pin helper; RESERVED_PAYLOAD_KEYS.md; X-03 clear: no tracked build/; 458 tests)
Done: E-17 @ 4474c1d (campaigns policy data pinned by schema; WATCH_ONLY/RECOMMEND no action; ASSISTED_DEAL draft-only offer.*/comms.* + step-up; BOUNDED_AUTOPILOT AUTOPILOT_NOT_AUTHORIZED even with valid limits; unknown level fail closed; campaign-sourced requests tainted, cannot skip approval; 598 tests)
Done: E-18 @ a5c8a98 (policy/trust vocabulary + reputation events + penalty ladder with appeal + payment boundary spec; validators reject bare 'verified' and evidence-less penalty; money.payment.* granted to nobody; 519 tests)
Done: E-19 @ 44f6d62 (jurisdiction pack format + eligibility(job, packs): missing pack/chain/threshold field/conflict/unresolved/expired => UNKNOWN; stale date_verified lowers confidence; uncertainty never removes a requirement; no local law hard-coded; synthetic sample:true fixture, no legal fact; 550 tests)
Done: X-03 (checked 2026-10-07: `git ls-files | grep ^build/` empty; build/ and *.egg-info/ are in .gitignore)
Done: B-04 lane-E half @ d3b9948 (02's fixture applies + blocks exactly that source; auto-apply decided, release human-only)

## Blockers
None. Everything below is optional follow-up or waits on Michael.

## Needs Michael decision
- MICHAEL_DECISIONS #1: real cash-at-risk and dollar caps. Shipped defaults are conservative data in `policy/policy.v1.json` (per flip $1,500, total $3,000, dry-run shadow caps; live spend is pinned at 0).
- `licenses_held` (which licenses Michael holds): needed for real jurisdiction packs (E-20).
- Host change: install gVisor (`runsc`) and Podman on the EliteDesk to run the sandbox spec (E-08). Not needed for the dry-run MVP.
- Payment provider choice and legal review (the boundary spec is provider-agnostic; no provider is selected).

## Needs coordinator review (Agent 01)
- ADR-05-003 (PROPOSED): confirms the merged 3-level PANIC and the Biscuit/SPIFFE deferral.
- The frozen example `action-request-email-held` carries `offer: 1050` under `comms.email.send`: the BINDING_UNDER_COMMS rule denies it. Regenerate it in ADR-0009.

## Proposed tasks (open; Agent 01 triages into READY_QUEUE)
| ID | Pri | Task | Acceptance |
|---|---|---|---|
| E-20 | P2 | **Real jurisdiction packs** in the E-19 format for the local pilot area (researched, cited, dated). Needs Michael's `licenses_held` and read-only web research. | `mbos-gov jurisdiction check` is clean with `sample:false` packs, each with a URL or `citation:` source, `verified_by`, `date_verified` and an honest `unresolved[]`. Every real pack is reviewed by a human before use. The no-hard-coded-local-law test still passes. A job class with no pack stays UNKNOWN. |
| E-21 | P2 | **License-gate wiring into the offer path** (after E-20): an outbound OFFER, COUNTER or quote for a license-gated job that Michael lacks a license for is blocked. | With an authoritative `needs_credential` result and no valid E-18 claim, `propose(offer.*)` is rejected with a LICENSE_GATE reason that cites the pack. An UNKNOWN or sample result routes to "ask Michael" and never auto-clears. An authoritative `eligible` result proceeds through the normal tier 0 + step-up path. Policy data, schema-pinned. Tests on lane D. |
| E-22 | P3 | Pin the LiteLLM key-API field names once a LiteLLM version is chosen (the generator's field names are INFERENCE). | A test against the pinned LiteLLM key API schema. |
| E-23 | P3 | Egress hostnames in `policy.egress.catalog` are INFERENCE: Agent 02 confirms them before any entry is enabled. | Each entry cites the provider documentation; enabling stays a reviewed schema + data change. |
| E-24 | P3 | Run the sandbox spec for real once the host has gVisor and Podman (E-08). | `mbos-gov sandbox check --host` reports `gvisor_ready: true`, and each component starts under its declared runtime. |
| (for 01) A-18 wiring | P1 | Replace `spine_d.set_kill_switch` with `spine_adapter.engage_panic/release_panic`, and register `schedule_reconcile` (call `.activate()` after `DBOS.launch()`). | See `docs/integration/05-spine-adapter-A18-call-sequence.md`. |

## Files
`src/mbos_governance/` (package), `policy/` (policy, content rules, sandbox, trust, jurisdiction data), `tests/` (598 tests on PostgreSQL 16), `tools/check_no_bypass.py`, `docs/governance/`, `docs/integration/`, `docs/decisions/ADR-05-003-*.md`, `docs/receipts/`.
