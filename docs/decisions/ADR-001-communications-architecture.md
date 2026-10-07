# Decision

Status: PROPOSED

## Context
The business OS needs a communications layer to talk with used-car sellers/customers on Michael's behalf (inbound/outbound phone, SMS, email, seller Q&A, intake, appointments, limited negotiation, transcripts, escalation). We must choose between hosted voice-AI platforms, building on CPaaS carriers directly, or a fully self-hosted open-source stack — and decide how to avoid lock-in while moving fast.

## Options considered
1. **Hosted orchestration** (Vapi or Retell on Twilio/Telnyx) — days to first call, MCP + warm transfer + transcripts built in; $0.07–0.31/min; data flows through a third party.
2. **Fully self-hosted** (LiveKit Agents / Pipecat + Telnyx SIP + Deepgram STT + Cartesia TTS + Postmark email) — ~$0.02–0.08/min, full data/latency ownership, no lock-in; weeks of build + real DevOps (K8s, failover, observability).
3. **Hybrid** — hosted orchestration now, but own the data plane (all transcripts/recordings/receipts into Michael's store via webhooks) and keep business logic behind a single Business-OS MCP server from day one.

## Recommendation
Adopt **Option 3 (hybrid)**: start on **Vapi (or Retell) + Telnyx** for speed, but from day one (a) route all transcripts/recordings/receipts into Michael's own store, and (b) expose inventory/CRM/scheduling/escalation as **one Business-OS MCP server** the orchestrator calls. This makes a later migration to the self-hosted stack (Option 2) move neither data nor tools. Prefer Telnyx as carrier (≈2× cheaper voice, official MCP, GA email) with Twilio ConversationRelay as fallback if its AI-voice maturity proves decisive in POC.

## Evidence
- Full research: docs/research/agent-06-communications.md
- Receipts: docs/receipts/receipt-01-hosted-platforms.md, receipt-02-cpaas-carriers.md, receipt-03-selfhosted-stack.md
- Vapi https://vapi.ai ; Retell https://www.retellai.com ; Telnyx https://telnyx.com/pricing/voice-api ; Twilio ConversationRelay https://www.twilio.com/docs/voice/conversationrelay/best-practices ; LiveKit https://docs.livekit.io/agents ; Pipecat https://github.com/pipecat-ai/pipecat
- Cost crossover: self-host wins TCO above ~100k–500k agent-min/month (vendor-blog estimate).

## Risks
- Hosted vendor pricing/lock-in and data passing through a third party (mitigated by owning data plane + MCP layer).
- Vendor latency/SLA numbers are optimistic; must verify on phone audio in POC.
- Carrier choice (Telnyx) has a thinner AI-voice track record than Twilio.

## Reversibility
Moderate-to-high if the hybrid discipline is followed: swapping orchestrators or carriers is contained because data + tools are owned. Low reversibility only if business logic gets embedded in a vendor.

## Coordinator review required: YES
(Depends on Agents 02/03/04 tool interfaces for the shared MCP server; do not mark ACCEPTED without Agent 01 cross-agent review.)
