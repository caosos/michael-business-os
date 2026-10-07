# Decision

ADR-0006 — Integration roles: CRM projection, n8n as connector, outbound ownership, approval channel

Status: ACCEPTED (2026-10-06, Agent 01). Item 4 (approval surface) was aligned on 2026-10-07 with `ROUND_ONE_SYNTHESIS.md` (Agent F, Operator UI).

## Context
- 07 named Twenty as the CRM that holds the lead record.
- 02 and 07 named n8n as the orchestrator.
- 06 and 07 both proposed sending email and SMS.
- 02 proposed ntfy/Apprise for notifications.
- Nobody chose how Michael actually receives and answers approvals.

## Decision
1. **CRM (C4; rubric 78.0 vs 59.0).** **Postgres is the system of record. Twenty is an optional one-way projection fed from the outbox**, consistent with 04's ADR-04-0001. 07's single hard requirement (one lead record with attribution plus API/webhooks) is met by Postgres `parties`/`leads`/`attribution` tables mirrored to Twenty. Edits made in Twenty do not flow back automatically. A Twenty edit becomes a proposed change that goes through an MCP write tool and produces a receipt. Twenty's AGPL-3.0 license is acceptable for internal, unmodified use (INFERENCE; no network distribution of modifications). EspoCRM is the fallback.
2. **n8n (C3; as backbone 51.0/90).** It is **demoted to an optional, sandboxed connector adapter.** It may be called *by* a DBOS step, through the Action Gateway, to reach an awkward third-party API. It owns no schedule of record, no state and no long-lived credentials (it gets per-call OpenBao leases), and every call it makes produces a receipt. Activepieces (MIT) replaces it if an OSI license is required. 02's collectors run as DBOS scheduled workflows that call `SourceAdapter` MCP tools.
3. **Outbound ownership (C12).** **Agent 06 owns every outbound effector**: Telnyx voice and SMS, Postmark email, and the consent/DNC ledger. **Agent 07 creates drafts and campaigns** that become ActionRequests executed through 06's effectors. As a result, 07's SMS review requests fall under TCPA, A2P 10DLC and STOP handling, and its email falls under CAN-SPAM, with all of these enforced once in 06's layer.
4. **Approval surface (C11; web UI 77.5, Telegram 78.0, ntfy 58.0: web and Telegram are a statistical tie).**
   - **Primary:** the **Operator UI** (ROUND_ONE_SYNTHESIS Agent F). It shows a dashboard, opportunity cards and a YES / NO / MODIFY / HOLD queue. It is also the step-up surface for money, irreversible actions and standing rules (WebAuthn/TOTP). The tie goes to the web UI because it scores higher on provenance and safety, and the synthesis already assigns it a build lane.
   - **Optional later:** a Telegram bot, bound to Michael's user ID, as a mobile notify-and-quick-decide channel for tier-0 reversible items only. MODIFY and step-up actions deep-link back into the Operator UI.
   - **ntfy is for one-way alerts only** (stuck runs, freezes, budget breaches). It never carries approvals because it does not authenticate the responder.
   - The `approval.schema.json` `channel` enum already covers `web`, `telegram` and `cli`.
5. **Business-domain vocabulary.** 06's used-car workflows (seller Q&A, title checks, price bands, curbstoning) are kept as the `project_vehicle` flip instance. 06 must add equivalent seller Q&A sets for the other flip categories and customer intake for services (ADR-0007).

## Evidence
- 04 §1 and §14; 07 ADR-07-0001/0002 (07 itself flags that n8n "may duplicate orchestration"); 06 §2, §12–14; 02 §3 and §11.
- Rubric: integration doc §3.

## Risks
- Twenty projection drift. Mitigation: rebuild it from the outbox, since Postgres is truth.
- An Operator UI outage blocks approvals. Mitigation: HOLD is the default on timeout (nothing executes), with a CLI fallback (`channel=cli`).

## Reversibility
High. Projections and channels are adapters.

Coordinator review required: NO. 06 and 07 must confirm the ownership split in round two.
