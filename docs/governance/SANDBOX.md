# Sandbox policy (E-08, ADR-0005 §7)

- **Spec:** `policy/sandbox.v1.json` (data)
- **Checker:** `src/mbos_governance/sandbox.py`, run as `mbos-gov sandbox check [--host]`
- **Status:** SPEC + CHECKER ONLY. Nothing is deployed.

## Principle
The model proposes and code authorizes. The **process boundary** is what makes the gateway's guard token more than an in-process convention (see ACTION_GATEWAY.md §7). Each MBOS process gets its own uid, its own database login and its own sandbox. Only the gateway holds the means to act on the outside world.

| Component | Kind | Runtime | Network | DB roles | Secrets |
|---|---|---|---|---|---|
| action-gateway | gateway | gVisor | egress proxy | gateway | `effector:*` (only holder) |
| spine-dbos | orchestrator | gVisor | DB only | agent_write, approver | none |
| operator-ui | operator_ui | gVisor | loopback only | approver | UI session key, PIN hash |
| discovery-adapters | source_adapter (untrusted input) | gVisor | egress proxy (E-07 catalog) | agent_write | `source:ebay_browse` |
| llm-agents | llm_agent (untrusted input) | gVisor | egress proxy (LiteLLM only) | agent_write | LiteLLM virtual key |
| model-generated-code | model_generated_code | **E2B** | **none** | none | none |

## Invariants the checker enforces (I1–I8)
- **I1.** Every component runs under gVisor or E2B, never directly on the host.
- **I2.** Model-generated code runs only in E2B, with no network, no secrets and no DB. E2B is used for nothing else.
- **I3.** Only the gateway holds `effector:*` secrets and the `gateway` DB role.
- **I4.** Components that read untrusted input are limited:
  - their DB roles are a subset of {agent_read, agent_write}
  - they hold no effector or UI secrets
  - they must declare `untrusted_input`
- **I5.** `approver` is limited to the Operator UI and the orchestrator. No running process holds `policy_admin`; publishing policy is a human CLI act.
- **I6.** Every component:
  - drops all Linux capabilities
  - is not privileged
  - has no host network and no container-socket mount
  - has a read-only root filesystem (E2B scratch excepted)
  - sets memory, CPU and PID limits
- **I7.** One uid per component, and the network mode comes from an allow-list.
- **I8.** Ids are unique, and owners are known agents.

## Host readiness (FACT, 2026-10-07)
`mbos-gov sandbox check --host` on the EliteDesk reports that `runsc`, `podman`, `docker` and `e2b` are **all absent**. Running this spec needs gVisor and a container runtime (Podman preferred) on the host. Installing them is a host change outside lane E, so it is a **Michael decision**, recorded in AGENT_STATUS. Until then the boundary is per-process Unix users and Postgres roles (lane D), and the checker keeps the spec honest.
