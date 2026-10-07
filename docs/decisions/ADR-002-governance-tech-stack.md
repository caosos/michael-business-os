# Decision

**ADR-002 — Governance tech stack: adopt durable-workflow + policy engine + capability tokens; build thin gateway/ledger**

Status:
PROPOSED

Context:
Given the control plane in ADR-001, which existing components should we adopt vs build?
This affects the whole system's dependency footprint, hosting model, and license posture,
so it needs coordinator review and alignment with Agent 01 and Agent 04.

Options considered:
- **Durable pause/resume substrate:** Temporal vs LangGraph interrupts vs Inngest / Restate
  / DBOS / Azure Durable Functions.
- **Policy decision point:** OPA/Rego vs Cedar vs Casbin vs Oso.
- **Capability/delegation tokens:** Biscuit vs macaroons vs bespoke.
- **Agent identity:** SPIFFE/SPIRE vs cloud IAM vs static keys.
- **Secrets:** Vault vs OpenBao vs cloud secret managers.
- **Approval UX:** HumanLayer vs OpenAI `needs_approval` vs LangGraph interrupts vs "AgentGate".

Recommendation:
- **Adopt Temporal** (MIT, self-hostable; indefinite Signal-waits + timeout) as the durable
  substrate — or **LangGraph** (MIT) if we stay in-process, respecting its re-run-from-top
  resume semantics.
- **Adopt OPA/Rego** (Apache-2.0, CNCF Graduated) as the PDP — or **Cedar** (Apache-2.0,
  formally verified) if formal assurance / AWS hosting is preferred. Avoid Oso (OSS lib
  deprecated Dec 2023). Casbin only if we want an embedded in-process check.
- **Adopt Biscuit** (Apache-2.0, public-key signed, offline attenuation) for capability and
  delegation tokens; macaroons as the symmetric fallback.
- **Adopt SPIFFE/SPIRE** (Apache-2.0) for agent workload identity if self-hosted; cloud IAM
  if cloud. Issue short-lived scoped tokens via OAuth2 token-exchange, never static keys.
- **Adopt Vault (BUSL-1.1) or OpenBao (MPL-2.0)** self-hosted, or cloud secret managers on
  cloud — dynamic short-lived secrets + encryption-as-a-service so raw secrets never enter
  agent/model context.
- **Borrow the pattern (not the dependency)** from HumanLayer / OpenAI `needs_approval` /
  LangGraph interrupts for approval UX. **Do NOT depend on "AgentGate"** (not a real
  standard; contested name across unrelated early-stage repos).
- **Build custom, kept thin:** the Action Gateway choke point, capability→effector mapping,
  Budget/Comms ledger, receipt-schema integration with Agent 04, trust-tagging/taint layer,
  and the kill switch.

Evidence:
- Verified URLs, licenses, and activity in docs/research/agent-05-governance.md §15 and the
  tooling-survey receipt docs/receipts/2026-10-06-governance-tooling-survey.md.
- HumanLayer product pivot and the "AgentGate" ambiguity are documented facts (§15.2).

Risks:
- **License:** Vault BUSL may be unacceptable → OpenBao mitigates. Confirm all licenses in-repo.
- **Hosting coupling:** Cedar/AVP and cloud IAM lean AWS; Temporal/OPA/Biscuit/SPIFFE are
  portable — final choice depends on the deployment-target decision (self-hosted vs cloud),
  which is a Michael decision.
- **Maturity:** CaMeL is a pattern with no production impl; we implement its principle via
  OPA + capabilities, not a library.

Reversibility:
Medium. The adopt choices are swappable behind the custom gateway/ledger (that is the point
of keeping the boundary custom and thin). Changing the durable substrate later is the most
expensive swap.

Coordinator review required:
YES
