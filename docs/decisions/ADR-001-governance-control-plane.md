# Decision

**ADR-001 — Governance control plane: single Action Gateway + external policy decision point**

Status:
PROPOSED

Context:
Every world-affecting action (messages, offers, money, purchases, publishing, scheduling,
price changes, calls, SMS, email, external commitments) must be gated behind Michael's
YES/NO/MODIFY/HOLD, while autonomous work (discover/research/score/draft) flows freely.
We need a single enforcement design that cannot be bypassed by any agent and that upholds
the core law: "No action without a receipt. No receipt without provenance." This decision
affects every specialist agent and the state layer, so it needs coordinator review.

Options considered:
1. **Per-agent self-enforcement** — each agent decides when to ask for approval. Rejected:
   no single choke point, trivially bypassed by a buggy/hijacked/misprompted agent, and
   impossible to audit uniformly.
2. **In-SDK HITL only** (CrewAI `human_input`, AutoGen `human_input_mode`, OpenAI
   `needs_approval`). Rejected as the whole answer: convenient but ship no durable
   storage/queue/UI and are framework-coupled; usable as a UX pattern, not as the trust
   boundary.
3. **Single Action Gateway choke point + external Policy Decision Point + execution guard**
   (chosen). Agents hold no effector credentials and can only submit an `ActionRequest`;
   a policy engine classifies allow/deny/needs_approval (default-deny); an execution guard
   re-checks approval validity, payload-hash equality, idempotency, budget, and kill-switch
   state at the moment of action. Maps onto the standard PEP/PDP/PIP split.

Recommendation:
Adopt option 3. Enforce authority structurally (agents literally lack the means to act
ungated), decide gating in a versioned external policy, and guard every execution. MODIFY
spawns a new request rather than mutating the original; the payload is hash-frozen at
propose time and re-verified at execution to defeat bait-and-switch. All decisions,
approvals, executions, and outcomes are appended to the receipt ledger.

Evidence:
- Full design: docs/research/agent-05-governance.md §3, §4, §7, §13.
- OWASP LLM Top 10 (LLM01), Simon Willison (lethal trifecta / dual-LLM), DeepMind CaMeL
  (arXiv:2503.18813) converge on "model proposes, non-LLM engine authorizes."
- PEP/PDP/PIP is the established XACML/OPA authorization pattern.

Risks:
- The gateway becomes a critical single component — must be highly available and fail-closed.
- Policy correctness is now safety-critical — mitigated by treating policies as tested,
  versioned artifacts.
- Adds latency/indirection to every action — acceptable for a human-gated system.

Reversibility:
Hard to reverse once agents and effectors are built around it, but the PEP/PDP split means
the decision engine itself can be swapped later without touching effectors. Medium-low
reversibility of the overall pattern; high reversibility of the specific engine choice.

Coordinator review required:
YES
