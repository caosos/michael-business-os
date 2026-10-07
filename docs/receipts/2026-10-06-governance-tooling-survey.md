# Receipt — Governance tooling survey

- Timestamp: 2026-10-06
- Agent: 05 (Governance / Security)
- Method: read-only web research (WebSearch + WebFetch) via two research sub-agents. No
  live external actions, no writes outside this branch.
- Related output: docs/research/agent-05-governance.md §14–§15; ADR-001; ADR-002.

Confidence legend: FACT = confirmed from the cited source; INFERENCE = my synthesis;
UNKNOWN = not verified / verify in repo.

## HITL & durable-workflow frameworks
| Source / URL | What was checked | Observed | Confidence |
|---|---|---|---|
| github.com/temporalio/temporal ; temporal.io/docs | license, HITL mechanism | MIT; workflow blocks on wait-condition, human Signal resolves it, waits indefinitely + durable timer for timeout; fork of Uber Cadence | FACT |
| docs.langchain.com/.../interrupts ; github.com/langchain-ai/langgraph | license, interrupt/resume | MIT; `interrupt()` + mandatory checkpointer, resume via `Command(resume=…)`; node re-runs from top on resume | FACT (license, mechanism); INFERENCE (activity) |
| inngest.com ; restate.dev ; dbos.dev ; learn.microsoft.com/azure/.../durable | HITL primitive | all expose "wait on external event/promise with timeout"; Azure DF extension MIT; others' licenses not pinned | FACT (mechanism); UNKNOWN (some licenses) |
| humanlayer.dev → humanlayer.com ; github.com/humanlayer/humanlayer | product state | original `@hl.require_approval()` Slack/email approval API; legacy repo README says code "pretty much all deprecated"; company pivoted to a coding-agent IDE | FACT |
| openai.github.io/openai-agents-python/human_in_the_loop | HITL mechanism | tools declare `needs_approval`; pending approvals as interruptions; serializable `RunState`; bring-your-own queue/storage/UI | FACT |
| "AgentGate" (multiple repos: RLASAF12, agentkitai, monteslu, AgentStaqAI, s1liconcow; agent-gate.dev, tryagentgate.com) | is it a citable project? | No single authoritative project; contested name across unrelated early-stage repos; not a standard | FACT |

## Policy engines
| Source / URL | Observed | Confidence |
|---|---|---|
| openpolicyagent.org ; github.com/open-policy-agent/opa | Apache-2.0; CNCF Graduated; JSON-in → allow/deny+obligations | FACT |
| cedarpolicy.com ; github.com/cedar-policy | Cedar lang+SDK Apache-2.0 (2023); formally verified; AVP managed/paid | FACT |
| casbin.org ; github.com/casbin/casbin | Apache-2.0; lightweight, embeddable multi-language | FACT (verify binding repo) |
| osohq.com | OSS lib deprecated Dec 2023; now hosted Oso Cloud | FACT (status); UNKNOWN (remaining OSS license) |
| github.com/permitio/opal | policy/data sync layer, not a decision engine; Apache-2.0 | FACT (role); verify license |

## Capability tokens
| Source / URL | Observed | Confidence |
|---|---|---|
| biscuitsec.org ; github.com/biscuit-auth/biscuit | Apache-2.0; public-key signed + offline attenuation + Datalog authz; v3.x Rust/WASM/Python/Haskell | FACT |
| Google "Macaroons" paper ; rescrv/libmacaroons (BSD-3) ; ecordell/pymacaroons (MIT) ; go-macaroon (BSD-3) | HMAC-chained bearer tokens, caveat attenuation, shared-secret verification | FACT |

## Agent identity
| Source / URL | Observed | Confidence |
|---|---|---|
| spiffe.io ; github.com/spiffe/spire | Apache-2.0; CNCF; short-lived SVID workload identity via Workload API | FACT |
| RFC 8707 (resource indicators), RFC 8693 (token exchange) | short-lived audience-bound scoped tokens | FACT |
| non-human / agent identity standards | active industry topic, unsettled; no single standard | FACT (that it's unsettled) |

## Secrets
| Source / URL | Observed | Confidence |
|---|---|---|
| vaultproject.io | BUSL-1.1 since v1.15 / Aug 2023 (no longer OSI-open); dynamic short-lived secrets; Transit encryption-as-a-service | FACT |
| github.com/openbao/openbao | MPL-2.0 Linux Foundation fork of Vault | FACT |
| aws.amazon.com/secrets-manager ; cloud.google.com/secret-manager | managed; KMS envelope encryption; auto-rotation | FACT |

## Prompt-injection references
| Source / URL | Observed | Confidence |
|---|---|---|
| genai.owasp.org (LLM Top 10, LLM01) | prompt injection #1 two editions; root cause = instructions+data share one channel; mitigations = segregate untrusted content, privilege restriction, HITL for sensitive ops | FACT |
| simonwillison.net/2023/Apr/25/dual-llm-pattern ; /tags/lethal-trifecta | dual-LLM quarantine pattern; lethal trifecta (private data + untrusted content + exfiltration); cannot filter/prompt your way out | FACT |
| arXiv:2503.18813 (CaMeL, DeepMind) ; arXiv:2506.08837 ; arXiv:2406.13352 (AgentDojo) | deterministic policy engine outside the model authorizes; model output treated as untrusted; no production reference impl | FACT (claims); UNKNOWN (production impl) |

## Uncertainty notes
- "Latest release" dates were generally not pinned — recency is approximate.
- Several licenses flagged UNKNOWN pending direct repo inspection (Inngest, Restate, DBOS,
  OPAL binding repo, residual Oso OSS, HumanLayer legacy).
- Another agent can reconstruct every §14–§15 claim and both ADRs from the URLs above.
