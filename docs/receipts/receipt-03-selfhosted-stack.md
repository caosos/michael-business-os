# Receipt — Self-hosted stack (media frameworks + STT/TTS + email)

- Timestamp: 2026-10-06
- Agent: 06 (Communications)
- Source: project repos/docs + third-party comparison/benchmark blogs (flagged).
- What was checked: LiveKit, Pipecat, Asterisk, FreeSWITCH, SIP trunking; STT (Deepgram/AssemblyAI/OpenAI/Google/Cartesia); TTS (Cartesia/ElevenLabs/Deepgram Aura/OpenAI/Rime/PlayHT); email APIs (Postmark/SES/Resend/Mailgun/SendGrid). Licenses, latency, cost, maturity.

## URLs checked
- LiveKit: https://docs.livekit.io/agents , https://github.com/livekit/agents
- Pipecat: https://github.com/pipecat-ai/pipecat
- Asterisk/FreeSWITCH licensing: https://rtcquickstart.org/guide/multi/pbx-asterisk-or-freeswitch.html , https://telcobridges.com/learning/sip-trunking/freeswitch-vs-asterisk/
- SIP trunk pricing: https://www.ringlyn.com/blog/sip-trunk-pricing-2026-comparison/ , https://telnyx.com/resources/sip-provider-comparison
- STT: https://futureagi.com/blog/speech-to-text-apis-in-2026-benchmarks-pricing-developer-s-decision-guide/ , https://www.gladia.io/blog/assemblyai-vs-deepgram
- TTS: https://futureagi.com/blog/best-text-to-speech-providers-2026/ , https://murf.ai/blog/cartesia-vs-elevenlabs , https://voiceaibench.com/
- Email: https://emailsendx.com/blog/amazon-ses-vs-sendgrid-vs-mailgun-vs-postmark-2026 , https://mailtrap.io/blog/best-inbound-email-api/ , https://www.agentmail.to/blog/best-inbound-email-apis-ai-agents
- Pipecat latency: https://futureagi.com/blog/how-to-optimize-pipecat-latency-2026/ , https://telnyx.com/resources/voice-ai-agents-compared-latency

## Observed (key facts)
- Licenses: LiveKit Apache-2.0 (first-class SIP bridge); Pipecat BSD-2 (verify on repo); Asterisk GPLv2 (copyleft on distribution); FreeSWITCH MPL (commercial-friendly).
- Maturity: LiveKit ~11k–21k★ across repos; Pipecat ~16k★.
- STT: Deepgram Nova-3 ~$0.0077/min streaming, TTFS ~247ms; AssemblyAI session-billed ~$0.0042/min; OpenAI 4o-transcribe $0.006 / mini $0.003.
- TTS: Cartesia Sonic TTFB ~40–90ms ~$37/1M; Deepgram Aura-2 ~90–115ms ~$30/1M; ElevenLabs premium naturalness.
- Email: Postmark best inbox placement (~83%) + best structured-JSON inbound parsing (ideal for seller replies); SES cheapest raw MIME; Resend best DX.
- End-to-end self-hosted voice: realistic ~0.8–1.5s voice-to-voice; LLM TTFT + endpointing dominate.

## Confidence
- HIGH on licenses and framework roles; MEDIUM on specific latency/price numbers (benchmark blogs, 2026-dated — verify on official pages + POC).

## Related output
docs/research/agent-06-communications.md §2.B, §4.3–4.6, §5, §6 ; ADR-001.

## Uncertainty
Cartesia STT per-minute price UNKNOWN; exact star counts/release versions vary by source; all latency/price need POC verification on phone audio.
