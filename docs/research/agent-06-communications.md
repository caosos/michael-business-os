# Agent 06 — Communications / Voice / SMS / Email

**Mission:** Research the future communications layer that can talk with sellers/customers on Michael's behalf under explicit approval and policy limits.

**Round One status:** RESEARCH ONLY. No calls, texts, emails, number provisioning, or deployment were performed. CAOSCare untouched.

**Date:** 2026-10-06
**Legend:** `FACT` = sourced claim (URL). `INFERENCE` = reasoning from facts. `RECOMMENDATION` = my advice. `UNKNOWN` = unverified / needs follow-up.
**Caveat:** Many pricing/latency numbers come from vendor or third-party comparison blogs (dated 2025–2026), not contractual docs. Treat specific figures as directional and re-verify against official pricing pages and a live POC before committing. Legal section is research, **not legal advice**.

---

## 0. Executive summary

- **Fastest path to a working demo (48h):** a *hosted* orchestration platform — **Vapi** or **Retell** — on top of **Twilio** (ConversationRelay) or **Telnyx** for telephony. Both expose MCP servers, warm transfer, transcripts, and sub-second latency targets. `RECOMMENDATION`
- **Best long-term owned stack:** **LiveKit Agents (Apache-2.0)** or **Pipecat (BSD-2)** + **Telnyx** SIP trunk + **Deepgram** STT + **Cartesia** TTS + **Postmark** email. Lower per-minute cost at scale, full data ownership, no vendor lock-in — at the price of real DevOps. `RECOMMENDATION`
- **Telephony carrier:** **Telnyx** is ~2× cheaper on voice than Twilio and ships an *official* MCP server + GA email API; **Twilio** has the most mature AI-voice tooling (ConversationRelay) and ecosystem. `FACT`
- **The hard part is not the tech — it's compliance.** AI voice is legally "artificial voice" under the TCPA (FCC, Feb 2024); recording consent, A2P 10DLC for SMS, CAN-SPAM for email, and contract-formation risk from an AI making offers all require a human-approval gate and mandatory disclosures. `FACT`/`INFERENCE`
- **Name check:** of the three ambiguous names in the brief — **AgentLine** = a real (very early) open-source AI phone API + thin hosted relay; **Patter** = a real open-source voice-AI SDK (more traction); **VoiceOS** = a category mismatch (desktop productivity assistant, *not* telephony). `FACT`

---

## 1. Landscape & name resolution

| Name in brief | What it actually is | Verdict for this use case |
|---|---|---|
| **Vapi** (vapi.ai) | Hosted voice-AI orchestration platform | Top hosted candidate `FACT` |
| **Retell** (retellai.com) | Hosted real-time voice-agent platform | Top hosted candidate `FACT` |
| **AgentLine** (github.com/AgentLineHQ, agentline.cloud) | OSS AI phone API (MIT, ~53★) + thin hosted relay | Early; viable only for self-host experiments `FACT` |
| **Patter** (getpatter.com) | OSS voice-AI SDK (MIT, ~1.1k★), BYO telephony | Early but more mature than AgentLine; self-host `FACT` |
| **VoiceOS** (voiceos.com) | Desktop productivity voice assistant (YC S25) | **Does not fit** — no telephony/SMS/API `FACT` |
| **Twilio / Telnyx** | CPaaS carriers (voice/SMS/email/numbers) | Telephony layer under any stack `FACT` |
| **SIP / Asterisk / FreeSWITCH** | Signaling protocol + OSS PBX/softswitch | Lower-level self-host options `FACT` |
| **LiveKit / Pipecat** | OSS real-time media + agent frameworks | Best owned-stack orchestration `FACT` |
| **STT/TTS/email APIs** | Deepgram/AssemblyAI; Cartesia/ElevenLabs/Deepgram Aura; Postmark/SES/Resend | Components of any stack `FACT` |

---

## 2. Recommended architectures

### 2.A — Hosted ("buy") — fastest to demo, lowest ops
```
PSTN ──► Twilio/Telnyx number ──► Vapi or Retell (STT+LLM+TTS orchestration)
                                      │  tools/function-calling ──► Business-OS MCP/REST (inventory, CRM, scheduling)
                                      │  warm transfer ──► Michael / human
                                      └─ webhooks ──► transcripts + recordings + receipts store
SMS ──► Twilio/Telnyx Messaging (A2P 10DLC) ──► same agent brain
Email ──► SendGrid (Twilio) / Telnyx Email / Postmark ──► inbound parse ──► agent
```
- Pros: live in days; MCP built-in; warm transfer, transcripts, recording out-of-the-box; vendor handles scaling/latency tuning.
- Cons: $0.07–$0.31/min all-in; data flows through a 3rd party; less control; SMS often needs the carrier's own messaging product wired alongside.
- `RECOMMENDATION`: start here for Round Two demo and first real seller conversations.

### 2.B — Self-hosted ("build") — owned stack, lowest run-rate at scale
```
PSTN ──► Telnyx SIP trunk ──► LiveKit SIP bridge ──► LiveKit Agent (or Pipecat pipeline)
                                                        ├─ STT: Deepgram Nova-3 (streaming)
                                                        ├─ LLM: Claude / fast model (streaming tokens)
                                                        ├─ TTS: Cartesia Sonic (or Deepgram Aura-2)
                                                        ├─ tools ──► Business-OS (MCP/REST)
                                                        └─ transfer ──► SIP REFER / bridge to human
SMS  ──► Telnyx Messaging API ──► agent
Email ──► Postmark (send + inbound JSON parse) ──► agent
Store ──► transcripts, recordings, receipts (owned DB + object storage)
```
- Pros: full ownership of recordings/transcripts/PII; ~$0.02–0.08/min marginal; swap any component; fits the "self-hosted AI business OS" mandate in the README.
- Cons: you own Kubernetes, failover, latency tuning, observability; longer build.
- `RECOMMENDATION`: target state once volume justifies it or data-ownership is non-negotiable. LiveKit (Apache-2.0, first-class SIP) is the more turnkey of the OSS options; Pipecat (BSD-2) if you want a lighter composable Python pipeline.

### 2.C — Hybrid (pragmatic middle)
Use hosted (2.A) for the live voice brain now, but **own the data plane** from day one: route all transcripts, recordings, and receipts into Michael's own store via webhooks, and keep the Business-OS tool layer (inventory/CRM/scheduling) behind your own MCP server. Migrating orchestration from hosted → self-hosted later then doesn't move your data or your tools. `RECOMMENDATION`

---

## 3. Self-hosted vs hosted comparison

| Dimension | Hosted (Vapi/Retell) | Self-hosted (LiveKit/Pipecat) |
|---|---|---|
| Time to first call | Days `INFERENCE` | Weeks `INFERENCE` |
| Marginal cost/min | ~$0.07–0.31 all-in `FACT` | ~$0.02–0.08 (STT+TTS+LLM+trunk) `INFERENCE` |
| Ops burden | Near-zero | High (you own scaling/SRE) `FACT` |
| Data ownership | Through vendor | Full `FACT` |
| Latency control | Vendor-tuned, good | Full control, tunable sub-1s `FACT` |
| Lock-in | Moderate–high | Low (swap components) `INFERENCE` |
| Compliance posture | Vendor BAA/SOC2 available (Retell) `FACT` | You own it entirely `INFERENCE` |
| License | Proprietary SaaS | Apache-2.0 / BSD-2 / MPL `FACT` |

**Crossover (`FACT`, vendor-blog estimate):** self-hosting voice tends to win on TCO above ~100k–500k agent-minutes/month once DevOps is priced in; below that, hosted is usually cheaper all-in.

---

## 4. Components — URLs, licenses, activity

### 4.1 Hosted orchestration platforms
- **Vapi** — https://vapi.ai — proprietary SaaS. Founded 2023; **$20M Series A (Dec 2024, Bessemer)**, ~$130M valuation; claims ~62M calls/mo, 99.99% SLA (enterprise). MCP ✓, warm transfer ✓, DTMF ✓, voicemail detection ✓. `FACT`
- **Retell AI** — https://www.retellai.com — proprietary SaaS. ~$5.1M total funding; **HIPAA + GDPR + SOC 2 Type I/II**, self-serve BAA on paid plans; MCP server shipped May 2025; warm transfer with announce ✓. `FACT`
- **AgentLine** — https://github.com/AgentLineHQ/AgentLine (MIT, ~53★, ~16 commits) + https://agentline.cloud. FastAPI + SignalWire/Twilio/Telnyx + Deepgram Nova-2 + Cartesia Sonic; native MCP server; inbound SMS. Warm human transfer undocumented. **Very early.** `FACT`/`UNKNOWN`
- **Patter** — https://www.getpatter.com + https://github.com/PatterAI/Patter (MIT, ~1.1k★). Python+TS SDK, 27+ integrations, BYO telephony (Twilio/Telnyx/Plivo), call transfer/DTMF/voicemail/barge-in, OpenTelemetry, built-in dashboard. **No hosted tier, no documented MCP/REST, SMS likely absent.** `FACT`/`UNKNOWN`
- **VoiceOS** — https://www.voiceos.com — desktop productivity assistant; **not telephony. Excluded.** `FACT`

### 4.2 CPaaS carriers
- **Twilio** — https://twilio.com. SLA 99.95% standard / 99.99% enterprise. Twilio Alpha MCP server (experimental, `@twilio-alpha/mcp`, 1,400+ endpoints). `FACT`
- **Telnyx** — https://telnyx.com. Owns private global backbone; SLA up to 99.999% (marketing; contractual likely 99.99%). **Official** MCP server (team-telnyx). GA Email API (Aug 2026). `FACT`

### 4.3 Self-hosted media/orchestration
- **LiveKit + Agents** — https://docs.livekit.io/agents — **Apache-2.0**; WebRTC SFU + first-class SIP bridge; ~11k–21k★ across repos, very active. `FACT`
- **Pipecat** — https://github.com/pipecat-ai/pipecat (by Daily) — **BSD-2-Clause** (verify on repo); ~16k★; composable Python STT→LLM→TTS pipeline, transport-agnostic. `FACT`
- **Asterisk** — **GPLv2** (copyleft on distribution of modified binaries); AI audio via ARI External Media / AudioSocket. `FACT`
- **FreeSWITCH** — **MPL** (commercial-friendly); AI audio via ESL + audio-fork; higher concurrency. `FACT`
- **SIP** — signaling protocol; a carrier SIP trunk (Telnyx/Twilio/Bandwidth/Plivo) connects the stack to the PSTN. `FACT`

### 4.4 STT (streaming)
- **Deepgram Nova-3** — ~$0.0077/min streaming; TTFS median ~247ms; common default in voice stacks. `FACT`
- **AssemblyAI Universal-3** — effective streaming ~$0.0042/min (session-billed → inflates short calls); very accurate. `FACT`
- **OpenAI gpt-4o-transcribe / mini** — $0.006 / $0.003/min; Whisper API is batch-only. `FACT`
- **Google Chirp 3**, **Cartesia Ink** — alternatives; Cartesia good if co-locating with its TTS. `FACT`/`UNKNOWN` (Cartesia STT per-min price unverified)

### 4.5 TTS (low latency)
- **Cartesia Sonic** — TTFB ~40–90ms (fastest class), ~$37/1M chars. `FACT`
- **Deepgram Aura-2** — ~90–115ms, ~$30/1M; best price/perf, reduces vendor count if STT is also Deepgram. `FACT`
- **ElevenLabs** — Flash ~75–200ms (~$60/1M), Multilingual v3 premium; best naturalness/voice library. `FACT`
- **OpenAI / Rime / PlayHT** — mid-latency alternatives. `FACT`

### 4.6 Email APIs
- **Postmark** — ~$84/mo @50K; **highest inbox placement (~83%)** + **best structured-JSON inbound parsing** (ideal for ingesting seller replies). `FACT` — `RECOMMENDATION` for this use case.
- **Amazon SES** — cheapest (~$0.10/1K) but raw MIME inbound, most setup. `FACT`
- **Resend** — best modern DX, 3K free/mo. `FACT`
- **Mailgun** — regex inbound routing, HMAC webhooks. `FACT`
- **SendGrid (Twilio)** — mature but lowest deliverability in cited test (~61%); convenient if already on Twilio. `FACT`

---

## 5. Cost model (illustrative, verify)

**Per-minute voice, all-in:**
- Hosted (Vapi/Retell): **$0.07–0.31/min** depending on chosen models/voices. `FACT`
- Self-hosted marginal: trunk (Telnyx ~$0.007 out / $0.0032 in) + STT (~$0.008) + TTS (~$0.004–0.01) + LLM (varies) + recording (~$0.002) ≈ **$0.02–0.08/min** + infra. `INFERENCE`

**Fixed / per-channel:**
- Phone number: Telnyx ~$1/mo; Twilio local $1.15, toll-free $2.15. `FACT`
- A2P 10DLC (SMS): brand ~$4.50–$46 one-time + campaign $15 vetting + ~$2–$10/mo; approval days–weeks. `FACT`
- SMS: ~$0.004 (Telnyx) / ~$0.0079 (Twilio) per segment + carrier pass-through. `FACT`
- Recording: Telnyx $0.002/min (free storage); Twilio $0.0025/min + $0.0005/min/mo storage. `FACT`
- Transcription: Telnyx $0.0015–0.027/min; Twilio Voice Intelligence ~$0.024–0.027/min (pricing page lists $0.05/min for basic). `FACT`
- Email: Postmark ~$84/mo @50K; SES ~$4.70 @50K; Resend 3K free/mo. `FACT`

---

## 6. Latency & reliability

- **Twilio ConversationRelay** (hosted STT+TTS pipe for AI): internal benchmark **median <0.5s, p95 <0.725s**, mouth-to-ear target **<1.2s**. `FACT`
- **Vapi:** targets p50 <500ms / p95 <800ms voice-to-voice (vendor); independent benches worse/variable (~720ms median, 1,558ms TTFAB in some tests). `FACT`
- **Retell:** ~600ms, generally sub-800ms (vendor/3rd-party). `FACT`
- **Self-hosted (LiveKit/Pipecat + Deepgram + Cartesia + fast LLM):** realistic voice-to-voice **~800ms–1.5s typical**, up to 2s+ unoptimized. **LLM time-to-first-token and endpointing/turn-detection dominate — not STT/TTS.** `FACT`/`INFERENCE`
- **Telnyx:** <200ms network round-trip across 18 PoPs (network only, not mouth-to-ear); full conversational latency comparable to Twilio ~1s. `FACT`/`UNKNOWN` (no published end-to-end bench)
- **SLA:** Twilio 99.95%/99.99%; Telnyx up to 99.999% (marketing); Vapi 99.99% (enterprise); Retell SLA only on enterprise. `FACT`

---

## 7. MCP / API compatibility

| Platform | REST | Webhooks | Tool/function calling | MCP server |
|---|---|---|---|---|
| Vapi | ✓ | ✓ | ✓ | ✓ `FACT` |
| Retell | ✓ | ✓ | ✓ | ✓ (May 2025) `FACT` |
| Telnyx | ✓ | ✓ | via AI Assistants | ✓ **official** `FACT` |
| Twilio | ✓ | ✓ (TwiML) | via ConversationRelay | ⚠️ alpha/experimental `FACT` |
| AgentLine | ✓ | ✓ (signed) | ✓ | ✓ `FACT` |
| LiveKit/Pipecat | (you build) | ✓ | ✓ (your code) | you expose your own `INFERENCE` |

`RECOMMENDATION`: Expose the Business-OS capabilities (inventory lookup, deal scoring, scheduling, CRM write, escalation) as **one MCP server** that any orchestration layer calls. This decouples the comms vendor from the business logic and makes 2.A→2.B migration cheap.

---

## 8. Phone-number provisioning

- **Telnyx:** local/toll-free from $1/mo; real-time self-serve purchase/port via portal + Numbers API, 100+ countries. `FACT`
- **Twilio:** local $1.15/mo, toll-free $2.15/mo; instant via Console or IncomingPhoneNumbers API. `FACT`
- **Gotchas (`FACT`):** usable for SMS requires A2P 10DLC (local) or toll-free verification; from **Feb 17, 2026** new toll-free verification needs three Business Registration Number fields. STIR/SHAKEN attestation (A/B/C) depends on number ownership/verification and affects spam-labeling of outbound caller ID.
- Round One: **do not provision live numbers** (per brief). `FACT`

---

## 9. Transcription & recording

- Both carriers and both hosted platforms provide **recording + real-time and batch transcription** natively. `FACT`
- Self-hosted: Deepgram/AssemblyAI streaming transcription inline in the pipeline; store audio in owned object storage. `INFERENCE`
- `RECOMMENDATION`: capture (a) full audio recording, (b) time-aligned transcript, (c) a structured post-call summary + extracted fields (price discussed, condition claims, next step) for every call — these are the raw material for receipts (§13) and human review.

---

## 10. Human handoff / escalation

- **Warm transfer** supported by Vapi, Retell (with announce), Patter; Twilio/Telnyx via conference bridge / `<Dial>` / Call Control; **SIP REFER** on both carriers (Twilio $0.10/refer, Telnyx $0.10/transfer). `FACT`
- `RECOMMENDATION` — escalation triggers: (1) counterpart asks for a human, (2) negotiation beyond approved band, (3) any binding commitment requested, (4) legal/complaint/anger signals, (5) agent low-confidence/repeated ASR failure, (6) off-topic/fraud signals. On trigger: warm-transfer to Michael if available, else take a message + schedule callback, always logging the reason.

---

## 11. Seller-question workflow (inbound answers + outbound inquiries)

1. **Trigger:** Michael (or deal-scoring agent) flags a listing worth pursuing → approves an outbound inquiry, OR a seller replies to one of our listings.
2. **Disclosure first:** "You're speaking with an automated assistant working for [Michael]; this call may be recorded." `RECOMMENDATION` (see §14).
3. **Structured Q&A:** agent asks the vetted question set — price/firmness, condition, mileage, title status (clean/salvage/lien), service history, accidents, reason for sale, availability for inspection.
4. **Photo/detail requests:** via SMS/email — request specific photos (VIN, odometer, title, damage areas) with a link/thread the inbound-parse email captures.
5. **Condition verification:** cross-check seller claims against listing + request evidence; flag discrepancies.
6. **Title/paperwork questions:** confirm title in hand, name match, lien payoff, registration/smog where relevant — **informational only; never give legal advice.**
7. **Capture:** every answer written to the deal record as structured fields + transcript + receipt.
8. **Escalate/approve:** anything price/commitment-related routes to Michael (§12).

## 11.b Customer-intake workflow (buyers)

1. Inbound buyer call/text/email → identity + what they're interested in.
2. Qualify: budget, financing/cash, trade-in, timeline, must-haves.
3. Match against inventory (MCP tool) → answer availability/condition/price (within approved band only).
4. Appointments: offer inspection/test-drive/pickup slots → write to calendar on confirmation.
5. Capture structured lead + transcript + summary + receipt; escalate on commitment/price/complaint.

---

## 12. Negotiation guardrails & approval points

**Guardrails (`RECOMMENDATION`):**
- Agent operates **only within a pre-approved price band** and term set per deal (floor/ceiling, max concessions, walk-away). No improvisation outside the band.
- **No binding offers/acceptances without explicit human approval** — because an AI's stated price can legally bind Michael (UETA/E-SIGN electronic-agent doctrine, §14.8). The agent may *propose* and *relay*, not *commit*.
- **Truthful scripts only** — no unqualified factual claims about a vehicle it can't verify; no false statements about identity, financing, or its own AI/human status (misrepresentation/UDAP risk).
- **Policy limits** encoded as hard constraints (not just prompt text): max offer, max messages/day per contact, allowed hours, allowed topics.

**Approval points (human-in-the-loop gates):**
1. Before any **outbound** first contact to a seller (consent/TCPA posture).
2. Before making/accepting any **offer or counteroffer** that could bind.
3. Before **scheduling** an in-person meeting at Michael's location/time.
4. Before sending **money-related** commitments (deposit, hold).
5. On any **escalation trigger** (§10).
6. Before **adding a new outbound channel** (new number, SMS campaign, email blast).

`RECOMMENDATION`: implement as an **approval queue** — agent drafts the action + rationale + receipt, Michael approves/edits/rejects (one tap), only then does it send. For live calls, the band is pre-approved so the call can proceed, but any out-of-band move pauses for approval or escalates.

---

## 13. Communication receipt schema (provenance)

Every inbound/outbound communication emits one immutable receipt. `RECOMMENDATION` — draft schema:

```json
{
  "receipt_id": "uuid",
  "schema_version": "1.0",
  "created_at": "ISO-8601",
  "channel": "voice | sms | email",
  "direction": "inbound | outbound",
  "deal_id": "ref to deal/opportunity",
  "contact": {
    "role": "seller | buyer | other",
    "number_or_email": "E.164 / email (stored per retention policy)",
    "state_or_region": "for consent-law determination",
    "consent": {
      "recording_disclosed": true,
      "ai_disclosed": true,
      "method": "spoken | written | implied-continued",
      "timestamp": "ISO-8601"
    }
  },
  "actor": {
    "mode": "autonomous | approved | human",
    "agent_id": "which agent",
    "model": "model id/version",
    "policy_band_id": "approved price/term band in effect",
    "approval": {
      "required": true,
      "approved_by": "Michael | none",
      "approved_at": "ISO-8601",
      "approval_ref": "queue item id"
    }
  },
  "content": {
    "summary": "one-paragraph outcome",
    "transcript_ref": "storage pointer",
    "recording_ref": "storage pointer | null",
    "extracted_fields": { "price_discussed": null, "title_status": null, "condition_claims": [], "next_step": null },
    "attachments": ["photo/doc refs"]
  },
  "negotiation": {
    "offer_made": null,
    "offer_received": null,
    "within_band": true,
    "binding": false
  },
  "escalation": { "triggered": false, "reason": null, "handed_to": null },
  "compliance_flags": ["tcpa_consent_basis", "dnc_checked", "a2p_registered", "canspam_footer"],
  "provider": { "vendor": "vapi|retell|twilio|telnyx|...", "provider_call_id": "...", "cost_usd": 0.0 },
  "integrity": { "prev_receipt_hash": "...", "this_hash": "..." }
}
```
`RECOMMENDATION`: hash-chain receipts (`prev_receipt_hash`) so the communication log is tamper-evident — this is the "provenance" backbone and the audit trail that both compliance and negotiation-liability defense depend on.

---

## 14. Legal / compliance considerations (US — research, NOT legal advice)

1. **Call recording consent** `FACT`: federal + ~35 states one-party; ~11 all-party (CA, DE, FL, IL, MD, MA, MT, NV, NH, PA, WA) + several mixed (CT, MI, OR, VT). `RECOMMENDATION`: **treat every call as all-party** — open with a spoken "this call may be recorded" and proceed on continued participation; verify affirmative-consent nuances per state before relying on implied consent.
2. **AI/bot disclosure** `FACT`: CA B.O.T. Act (SB 1001) targets large platforms (likely not 1:1 calls, but spirit applies); Utah UAIP requires disclosure on direct ask / high-risk; Colorado's general duty was repealed (2026). `RECOMMENDATION`: **always disclose it's an automated AI assistant acting for Michael.**
3. **TCPA + FCC AI-voice ruling (Feb 8, 2024)** `FACT`: **AI-generated voice = "artificial voice"** → calls/texts to cell phones need prior express consent (prior express *written* consent for marketing), caller identification, and opt-out. Penalties $500–$1,500 **per** call/text, uncapped, private right of action. `INFERENCE`: a seller publicly listing a car arguably makes an inquiry call "solicited/informational," but that **does not clearly waive** the artificial-voice consent requirement — **genuinely gray, get counsel.** Fifth Circuit (*Bradford*, Feb 2026) rejected the written-consent rule *only* in TX/LA/MS.
4. **A2P 10DLC (SMS)** `FACT`: mandatory brand+campaign registration via TCR to send business SMS; needs business identity (EIN friction for pure sole proprietors); capture opt-in, honor STOP.
5. **CAN-SPAM (email)** `FACT`: truthful headers, ad identification, valid physical postal address, one-step unsubscribe honored ≤10 business days; up to ~$53k per email.
6. **Do-Not-Call** `FACT`: bites on telemarketing; EBR exemption **does not** rescue AI/prerecorded calls; always honor individual do-not-call requests. `INFERENCE`: pure inquiry-about-a-specific-listing is likely outside core DNC, but scrub if outreach shades into solicitation.
7. **Privacy / recording storage** `FACT`/`INFERENCE`: CCPA/CPRA treats recordings as PI and voiceprints as biometric, but business thresholds (e.g. >$25M revenue) likely exempt a small operation initially; GDPR only if EU data. Best practice: minimize retention, secure storage, **don't build voiceprints.**
8. **Negotiation / agency** `FACT`: under **UETA §14 / E-SIGN**, an electronic agent can **form binding contracts attributed to the human user** — "the machine binds the user." `INFERENCE`: this is exactly why the **human-approval gate before any binding offer** (§12) is load-bearing, not optional. Watch state auto-dealer licensing / "curbstoning" if volume grows.

**Compliance checklist (synthesized `RECOMMENDATION`):** disclose AI + recording at contact start → treat calls all-party → avoid u-consented AI-voice/autodial outreach, prefer responses to specific listings + get counsel → register A2P 10DLC + honor STOP → CAN-SPAM footer + unsubscribe → DNC-scrub any solicitation → minimize/secure data, no voiceprints → human approval before any binding commitment → log everything as receipts.

---

## 15. 48-hour demo path (Round Two — requires explicit approval before any execution)

> This is a *plan*, not an action. Nothing below runs until Michael approves — and live provisioning/calling must also clear the compliance gates in §14.

**Goal:** an end-to-end voice+SMS+email agent that can answer a seller's questions, request photos, and escalate — demoed against **test numbers / Michael's own phone only** (no cold outbound to real sellers in the demo).

**Hour 0–4 — Decide & scaffold**
- Pick hosted path **Vapi or Retell** + **Telnyx** (cheaper, official MCP) or **Twilio ConversationRelay** (most mature). `RECOMMENDATION`: Vapi + Telnyx.
- Stand up the **Business-OS MCP server** stub exposing: `lookup_inventory`, `get_deal`, `write_deal_note`, `propose_offer`, `schedule_appointment`, `escalate_to_human`.
- Provision **one test number** (Telnyx) — *with approval* — restricted to test contacts.

**Hour 4–16 — Voice agent**
- Configure agent system prompt with disclosure script, seller Q&A set (§11), approved price band, escalation triggers.
- Wire tool/function calls to the MCP server; enable recording + transcription + webhook to receipts store.
- Configure warm transfer to Michael's cell.

**Hour 16–28 — SMS + email**
- SMS: use test-number messaging for photo/detail requests (A2P registration started in parallel — note multi-day approval; demo on test/allowlisted numbers meanwhile). `FACT`: 10DLC won't fully clear in 48h.
- Email: **Postmark** sending + inbound parse → thread photos/replies into the deal record with a CAN-SPAM footer.

**Hour 28–40 — Receipts, approval queue, guardrails**
- Implement the receipt schema (§13) + hash-chain; log every turn.
- Implement the approval queue: agent drafts offers → Michael approves before send; out-of-band negotiation pauses/escalates.

**Hour 40–48 — Scripted demo + review**
- Run 3 scripted scenarios against Michael's own phone/test numbers: (1) seller answers condition/title questions + photo request; (2) buyer intake + appointment booking; (3) negotiation that hits the band ceiling → escalation + approval.
- Produce the demo artifact: transcripts, recordings, receipts, and a one-page "what worked / latency / cost / compliance gaps" review.

**Explicitly out of scope for the 48h demo:** cold outbound to real sellers, production A2P throughput, anything touching CAOSCare.

---

## 16. Open UNKNOWNs / follow-ups before Round Two

- `UNKNOWN` Exact Telnyx Email per-message price; Cartesia STT per-minute price.
- `UNKNOWN` Real end-to-end mouth-to-ear latency for each option on *phone audio* — must benchmark in POC; vendor numbers are optimistic.
- `UNKNOWN` TCPA "solicited inquiry" theory for AI-voice calls to sellers — **needs a licensed attorney**; this is the single biggest legal risk.
- `UNKNOWN` Whether Michael has/needs an EIN/business entity for A2P 10DLC registration (affects SMS throughput and timeline).
- `UNKNOWN` Current exact GitHub stars/release versions and SLAs — re-verify against repos/contracts at build time.
- `UNKNOWN` Auto-dealer licensing / curbstoning exposure if transaction volume grows.
- `UNKNOWN` Which LLM/model Michael wants as the agent brain (affects latency + cost + quality).

---

*Prepared by Agent 06 (Communications). Research only — no live communications were sent. Figures and legal points require re-verification before any deployment.*
