# Agent Status

Agent: 06
Role: Communications (voice / SMS / email layer)
Branch: research/agent-06-communications
Worktree: /home/michaelos/business-os-worktrees/agent-06-communications
State: WORKING
Current phase: Round Two — Wave One, build lane F (Operator UI / approval UX)
Started: 2026-10-06
Last updated: 2026-10-07

## Current objective
ROUND TWO (2026-10-07): build the minimal Operator UI (opportunity cards, YES/NO/MODIFY/HOLD) against the frozen v1.0.0 contracts from `research/agent-01-coordinator` @ `acb6f3b`. Dry-run only; no live SMS/email/voice.

Round One (historical): Round-One research on the future communications layer (inbound/outbound phone, SMS, email, seller Q&A, customer intake, negotiation guardrails, approvals, receipts, compliance) is complete and committed. No live communications performed.

## Completed
- Researched hosted voice-AI platforms: Vapi, Retell, AgentLine, Patter, VoiceOS.
- Researched CPaaS carriers: Twilio, Telnyx (voice, SMS, email, numbers, recording, transcription, SIP, compliance mechanics).
- Researched self-hosted stack: LiveKit, Pipecat, Asterisk, FreeSWITCH, SIP + STT/TTS + email APIs.
- Researched US legal/compliance: recording consent, AI-voice (FCC/TCPA), A2P 10DLC, CAN-SPAM, DNC, privacy, agency/contract-formation.
- Produced architectures (hosted / self-hosted / hybrid), cost + latency models, MCP/API matrix, workflows, negotiation guardrails, approval points, receipt schema, 48h demo path.
- Wrote final research file, 2 decision records, and 4 provenance receipts.

## Findings
- **Name resolution** (FACT): AgentLine = early OSS AI-phone API (MIT, ~53★) + thin hosted relay; Patter = OSS voice SDK (MIT, ~1.1k★, no hosted tier); **VoiceOS = category mismatch (desktop assistant, not telephony) — excluded.**
- **Hosted leaders** (FACT): Vapi ($20M Series A, MCP, warm transfer, ~0.5s target) and Retell (HIPAA/SOC2, MCP, warm transfer).
- **Carriers** (FACT): Telnyx ≈2× cheaper on voice, official MCP, GA email API; Twilio most mature AI-voice tooling (ConversationRelay, median <0.5s) + ecosystem.
- **Owned stack** (FACT): LiveKit (Apache-2.0, first-class SIP) or Pipecat (BSD-2) + Deepgram STT + Cartesia/Deepgram-Aura TTS + Postmark email.
- **Cost** (FACT/INFERENCE): hosted ~$0.07–0.31/min; self-hosted marginal ~$0.02–0.08/min; number ~$1/mo; A2P 10DLC ~$4.50–$46 + ~$2–10/mo.
- **Latency** (FACT/INFERENCE): hosted ~0.5–0.8s, self-hosted ~0.8–1.5s voice-to-voice; LLM TTFT + endpointing dominate.
- **Compliance (critical, FACT)**: FCC (Feb 2024) ruled AI voice = "artificial voice" under TCPA → consent/ID/opt-out, $500–$1,500 per call/text uncapped. Treat all calls as all-party recording consent. A2P 10DLC required for SMS; CAN-SPAM for email. UETA/E-SIGN: an AI can form contracts binding Michael.

## Decisions made
- ADR-001 (PROPOSED): hosted-first → hybrid comms architecture (Vapi/Retell + Telnyx, own data plane + MCP tool layer from day one).
- ADR-002 (PROPOSED): mandatory human-approval gate before any binding offer + mandatory AI/recording disclosure; hash-chained receipts for all comms.
- Both flagged for coordinator review (overlap with Agent 05 governance).

## Unknowns
- TCPA "solicited inquiry" theory for AI-voice calls to sellers — needs a licensed attorney (biggest legal risk).
- Does Michael have/need an EIN/business entity for A2P 10DLC (gates SMS throughput/timeline)?
- Real mouth-to-ear latency on actual phone audio per option — must benchmark in POC.
- Which LLM is the agent brain (affects latency/cost/quality).
- Exact Telnyx Email per-message price; Cartesia STT per-minute price.
- Auto-dealer licensing / curbstoning exposure at volume.

## Blockers
None currently.

## Needs Michael decision
- Legal risk appetite / engage counsel on TCPA AI-voice-to-sellers question before any outbound calling.
- Business entity / EIN status for A2P 10DLC SMS registration.
- Build-vs-buy preference for Round Two (recommend hosted-first hybrid).

## Needs coordinator review
- ADR-001 (comms architecture) and ADR-002 (approval gate + disclosure + receipts) — the approval gate and receipt schema overlap with Agent 05 (governance) and Agent 04 (CRM/state). Receipt schema should be reconciled project-wide.
- Shared MCP "Business-OS tool server" assumption (inventory/CRM/scheduling/escalate) depends on Agents 02/03/04 interfaces.

## Files produced
- docs/research/agent-06-communications.md (full Round-One research)
- docs/decisions/ADR-001-communications-architecture.md
- docs/decisions/ADR-002-approval-gate-and-receipts.md
- docs/receipts/receipt-01-hosted-platforms.md
- docs/receipts/receipt-02-cpaas-carriers.md
- docs/receipts/receipt-03-selfhosted-stack.md
- docs/receipts/receipt-04-legal-compliance.md
- docs/status/AGENT_STATUS.md (this file)

## Next action
Round One complete. Awaiting coordinator (Agent 01) review of ADRs and Michael's decisions on legal counsel + build-vs-buy before any Round Two work. Will not place calls/texts/emails or provision numbers.
