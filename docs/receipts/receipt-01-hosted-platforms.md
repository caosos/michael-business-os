# Receipt — Hosted voice-AI platforms

- Timestamp: 2026-10-06
- Agent: 06 (Communications)
- Source: web research (vendor pages + third-party comparison blogs)
- What was checked: Vapi, Retell, AgentLine, Patter, VoiceOS — capabilities, pricing, latency, API/MCP, transcription, handoff, maturity, license.

## URLs / repositories checked
- Vapi: https://vapi.ai , https://vapi.ai/blog/speech-latency , https://vapi.ai/platform ; Series A https://www.bvp.com/news/our-investment-in-vapi-the-voice-ai-developer-platform ; pricing (3rd party) https://www.cloudtalk.io/blog/vapi-ai-pricing/
- Retell: https://www.retellai.com , https://www.retellai.com/pricing , https://docs.retellai.com/general/compliance ; review https://synthflow.ai/blog/retell-ai-review
- AgentLine: https://github.com/AgentLineHQ/AgentLine , https://agentline.cloud
- Patter: https://www.getpatter.com , https://github.com/PatterAI/Patter
- VoiceOS: https://www.voiceos.com

## Observed (key facts)
- Vapi: orchestration over STT/LLM/TTS; MCP + warm transfer + DTMF; latency target p50<500ms/p95<800ms (vendor); $20M Series A (Dec 2024, Bessemer); proprietary. All-in ~$0.07–0.25+/min.
- Retell: real-time voice platform; MCP server (May 2025); warm transfer w/ announce; HIPAA+GDPR+SOC2, self-serve BAA; ~$5.1M funding; ~$0.07–0.31/min.
- AgentLine: MIT OSS (~53★, ~16 commits) + hosted relay (number $2/mo, voice $0.10/min, inbound SMS $0.02); native MCP; **very early**.
- Patter: MIT OSS SDK (~1.1k★), 27+ integrations, BYO telephony; no hosted tier / no documented MCP/REST; SMS likely absent.
- VoiceOS: desktop productivity assistant (YC S25) — **NOT telephony; excluded.**

## Confidence
- HIGH that VoiceOS is a category mismatch; HIGH on Vapi/Retell being the mature hosted options.
- MEDIUM on specific pricing/latency numbers (many from third-party blogs, not contracts).

## Related output
docs/research/agent-06-communications.md §1, §4.1, §6, §7 ; ADR-001.

## Uncertainty
Vendor latency/SLA figures are optimistic; SMS specifics for Vapi/Retell/Patter not firmly documented; AgentLine human warm-transfer unverified.
