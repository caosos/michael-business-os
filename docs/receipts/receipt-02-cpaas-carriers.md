# Receipt — CPaaS carriers (Twilio / Telnyx)

- Timestamp: 2026-10-06
- Agent: 06 (Communications)
- Source: official pricing/docs pages (verified directly) + some third-party aggregators (flagged).
- What was checked: number provisioning, voice/SMS/email pricing, recording/transcription, DTMF/transfer, media streaming for AI, API/MCP, SLA, SIP, compliance mechanics.

## URLs checked
- Twilio: https://www.twilio.com/en-us/voice/pricing/us , https://www.twilio.com/docs/voice/conversationrelay/best-practices , https://support.twilio.com/hc/en-us/articles/1260803965530-Pricing-and-Fees-for-A2P-10DLC-Service , https://www.twilio.com/en-us/legal/service-level-agreement/twilio-apis
- Telnyx: https://telnyx.com/pricing/voice-api , https://telnyx.com/pricing/elastic-sip , https://developers.telnyx.com/docs/inference/ai-assistants/realtime-conversations , https://telnyx.com/release-notes/email-api-now-generally-available , https://support.telnyx.com/en/articles/5634625-10dlc-fees-and-charges , https://developers.telnyx.com/docs/messaging/toll-free-verification

## Observed (key facts, verified on official pages)
- Numbers: Twilio local $1.15/mo, TF $2.15/mo; Telnyx from $1/mo. Instant self-serve via API.
- Voice US: Twilio inbound local $0.0085 / outbound $0.014 / SIP $0.004; Telnyx ~$0.007 out / $0.0032 in. Telnyx ≈2× cheaper.
- Recording: Twilio $0.0025/min + storage; Telnyx $0.002/min free storage.
- Transcription: Twilio Voice Intelligence ~$0.024–0.027/min (page lists $0.05/min basic); Telnyx $0.0015–0.027/min.
- Real-time AI: Twilio ConversationRelay (median <0.5s, p95 <0.725s, mouth-to-ear <1.2s); Telnyx AI Assistants + Conversation Relay over WebSocket; Telnyx network RTT <200ms.
- MCP: Telnyx **official** server; Twilio **alpha/experimental** (@twilio-alpha/mcp).
- Email: SendGrid (mature) ; Telnyx Email **GA Aug 2026** (corrects assumption Telnyx has no email).
- SLA: Twilio 99.95%/99.99%; Telnyx up to 99.999% (marketing).
- Compliance: both enforce A2P 10DLC (TCR), STIR/SHAKEN, toll-free verification (new Business Registration Number fields from Feb 17, 2026).

## Confidence
- HIGH on voice/number/recording/SIP/media-stream rates (verified on official pricing pages).
- MEDIUM on SMS base rates, SLA tiers, timelines (some third-party sources).

## Related output
docs/research/agent-06-communications.md §4.2, §5, §6, §7, §8 ; ADR-001.

## Uncertainty
Exact Telnyx Email per-message price UNKNOWN; Telnyx end-to-end mouth-to-ear latency not published.
