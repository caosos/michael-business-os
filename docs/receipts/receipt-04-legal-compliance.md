# Receipt — Legal / compliance (US)

- Timestamp: 2026-10-06
- Agent: 06 (Communications)
- Source: government sites + reputable law-firm / vendor summaries. **Research only — NOT legal advice.**
- What was checked: call-recording consent, AI/bot disclosure, TCPA + FCC AI-voice ruling, A2P 10DLC, CAN-SPAM, DNC, privacy (CCPA), agency/contract formation.

## URLs checked
- Recording consent: https://www.rev.com/blog/phone-call-recording-laws-state , https://omnilawpc.com/two-party-consent-states/
- CA B.O.T. Act: https://perkinscoie.com/insights/update/i-am-robot-californias-new-law-requires-disclosure-use-bots
- FCC AI-voice ruling (Feb 8, 2024): https://www.wiley.law/alert-FCC-Extends-Regulatory-Reach-Over-AI-Announces-TCPA-Restrictions-Cover-AI-Generated-Voices-in-Outbound-Calls , https://www.wsgr.com/en/insights/fcc-rules-ai-generated-voices-are-artificial-under-the-tcpa.html
- Utah UAIP: https://fpf.org/blog/chatbots-in-check-utahs-latest-ai-legislation/ ; Colorado repeal context: Davis Polk
- TCPA penalties: https://www.plura.ai/articles/tcpa-penalties-and-fines ; 5th Cir. Bradford: https://www.hklaw.com/en/insights/publications/2026/03/tcpa-reset-fifth-circuit-rejects-prior-express-written-consent-rule
- A2P 10DLC: https://signalwire.com/blog/a-beginners-guide-to-a2p-10dlc-campaign-registration , https://www.nextiva.com/blog/what-is-a2p-10dlc.html
- CAN-SPAM: https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business
- DNC/TSR: https://www.ftc.gov/business-guidance/resources/complying-telemarketing-sales-rule
- CCPA biometrics: https://www.termsfeed.com/blog/ccpa-biometrics/
- Electronic-agent contracts (UETA/E-SIGN): https://astraea.law/insights/ai-agent-contract-formation-electronic-agents

## Observed (key facts)
- Recording consent: federal + ~35 states one-party; ~11 all-party (CA, DE, FL, IL, MD, MA, MT, NV, NH, PA, WA) + mixed (CT, MI, OR, VT). Conservative rule: treat all calls all-party.
- **FCC (Feb 8, 2024): AI-generated voice = "artificial voice" under TCPA** → consent + caller identification + opt-out required.
- TCPA penalties: $500–$1,500 per call/text, uncapped, private right of action. 5th Cir. (Bradford, Feb 2026) rejected PEWC rule only in TX/LA/MS.
- CA B.O.T. Act scoped to large platforms (≥10M visitors); Utah UAIP = disclose on direct ask / high-risk; Colorado general duty repealed (2026).
- A2P 10DLC mandatory for business SMS (TCR brand+campaign); needs business identity.
- CAN-SPAM: truthful headers, physical address, one-step unsubscribe ≤10 business days; up to ~$53k/email.
- DNC: bites on telemarketing; EBR does NOT rescue AI/prerecorded calls.
- CCPA: recordings = PI, voiceprints = biometric; small operator likely under business thresholds initially.
- **UETA §14 / E-SIGN: an electronic agent can form contracts attributed to (binding) the human user.**

## Confidence
- HIGH on the existence/substance of FCC ruling, TCPA penalties, CAN-SPAM, A2P 10DLC, UETA/E-SIGN.
- MEDIUM/UNKNOWN on application to this exact use case (AI-voice "solicited inquiry" to sellers) — genuinely unsettled, needs counsel.

## Related output
docs/research/agent-06-communications.md §12, §14, §16 ; ADR-002.

## Uncertainty
"Solicited inquiry" status of AI-voice calls to sellers = biggest open legal risk. State-by-state recording-consent mechanics and emerging AI-disclosure bills need re-check near launch. Auto-dealer licensing/curbstoning at volume UNKNOWN.
