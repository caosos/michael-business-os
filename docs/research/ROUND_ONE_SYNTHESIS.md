# ROUND ONE SYNTHESIS — Michael Business OS

Date: 2026-10-07  
Status: ROUND ONE COMPLETE  
Owner: Michael  
Coordinator synthesis: Aria / Agent 01 lane

## Executive decision

Build a **Python-first, Postgres-centered, self-hosted Business OS** with a durable workflow spine and a strict approval/action boundary.

The system should be useful before it is broad.

The first usable product is not CRM, voice, marketing automation, or a giant scraper fleet.

The first usable product is:

**real opportunities in → normalized → economically scored → ranked → shown to Michael → Michael decides YES/NO/MODIFY/HOLD → action remains dry-run → receipt/provenance recorded.**

Once that loop is trustworthy, add real outbound actions one lane at a time.

---

## Unified architecture

```text
SOURCES
  official APIs
  email alerts / IMAP
  sanctioned feeds
  isolated browser collectors later
        │
        ▼
SOURCE ADAPTERS
        │
        ▼
NORMALIZER + DEDUP
        │
        ▼
POSTGRES SYSTEM OF RECORD
  opportunities
  comps
  scorecards
  approvals
  receipts
  provenance
  outcomes
  outbox
        │
        ▼
DBOS DURABLE WORKFLOW
DISCOVER
→ NORMALIZE
→ RESEARCH
→ SCORE
→ RECOMMEND
→ APPROVAL GATE
→ ACT
→ RECEIPT
→ OUTCOME
→ LEARN
        │
        ├── MCP tool boundary
        ├── governance / policy checks
        ├── communications service
        └── marketing adapters
        │
        ▼
MICHAEL
YES / NO / MODIFY / HOLD
```

---

## Final component decisions

### 1. Implementation language
**Decision: Python.**

Why:
- best fit across DBOS/Pydantic AI/LangGraph/data collection/scoring
- easiest path to rapid MVP
- strong ecosystem for scraping, APIs, analytics, Postgres, and AI tooling
- keeps implementation coherent across opportunity/scoring/state layers

### 2. System of record
**Decision: PostgreSQL.**

Postgres owns authoritative business state.

No CRM gets to become a second source of truth.

### 3. Durable workflow engine
**Decision: DBOS for MVP.**

Temporal remains a documented scale-out option.

Reason:
- lower single-operator burden
- same-Postgres architecture
- strong fit with durable waits/queues/cron
- easier first deployment on the EliteDesk

### 4. Agent/tool boundary
**Decision: MCP.**

Every consequential tool invocation should carry identity/scope into provenance.

### 5. CRM
**Decision: no heavy CRM in the first vertical slice.**

Build the canonical business-state model first.

Later options:
- thin custom operator UI
- Twenty / EspoCRM / other projection only if the benefit exceeds the maintenance/license cost

### 6. n8n
**Decision: edge automation only, not core orchestration.**

Suitable later for marketing/integration glue.

Do not place canonical business state or approval correctness inside n8n.

### 7. Opportunity discovery
**Decision: staged source strategy.**

Priority order:
1. official APIs
2. sanctioned email alerts / IMAP
3. public/internal endpoints after testing and explicit policy
4. headless/browser automation only when the economics justify the maintenance/risk
5. manual-only for sources where automation is inappropriate

First implementation candidates:
- eBay Browse API
- GSA Auctions API
- Trash Nothing API
- IMAP alert ingestor
- Craigslist collector as an isolated experimental adapter after live testing

### 8. Economics engine
**Decision: hard gates first, composite score second.**

Primary discipline metric:
**expected net profit per Michael-hour**

Supporting metrics:
- expected value
- cash required
- ROI
- distance/travel cost
- time-to-cash
- confidence
- downside/salvage value
- scarcity
- skill fit

Every score must retain:
- formula/config version
- input provenance
- confidence
- explanation

### 9. Governance
**Decision: model proposes; non-model policy layer authorizes.**

Initial autonomous scope:
- discovery
- research
- normalization
- comps
- scoring
- ranking
- drafting

Initial approval-required scope:
- messages
- offers
- purchases
- spending
- publishing
- scheduling
- phone
- SMS
- email
- price changes
- contractual commitments

### 10. Communications
**Decision: one communications subsystem later.**

Marketing does not send directly.

Preferred later direction:
- hosted-first/hybrid for speed and reliability
- own data/receipts remain in Business OS
- AI/recording disclosure and legal controls built in
- voice/SMS not part of the first MVP

### 11. Marketing
**Decision: organic-first.**

Priority:
- website/service pages
- local SEO
- Google Business Profile
- reviews
- Apple/Bing manual presence
- attribution
- referrals/contractor relationships
- API-driven publishing only after approval workflow exists

No spam engine.

---

## Unified canonical objects

### Opportunity
Minimum fields:
- id
- source
- source_listing_id
- source_url
- ingestion_method
- source_risk
- raw_payload_hash
- type
- category
- title
- description
- condition
- price
- fees/premium
- location
- distance
- seller/contact metadata
- images
- first_seen
- last_seen
- status
- dedup_key
- provenance_refs

### Research / Comps
- comp source
- observed/sold value
- date
- condition
- distance
- confidence
- source URL/reference

### Scorecard
- acquisition_cost
- parts_materials
- fees
- travel_cost
- travel_time
- labor_hours
- expected_revenue
- expected_net_profit
- expected_value
- profit_per_hour
- ROI
- time_to_cash
- risk
- confidence
- skill_fit
- scarcity
- downside_value
- composite_score
- config_version
- provenance_refs

### Recommendation
- recommendation_id
- opportunity_id
- decision: YES | MAYBE | PASS
- rationale
- recommended_action
- estimated_cost
- confidence
- expires_at
- scorecard_ref

### Approval
- approval_id
- action_id
- decision: YES | NO | MODIFY | HOLD
- modifications
- decided_by
- decided_at
- payload_hash
- expires_at

### ActionRequest
- action_id
- requested_by
- type
- target
- payload
- payload_hash
- required_capability
- estimated_cost
- approval_required
- approval_ref
- idempotency_key

### Receipt
- receipt_id
- action_id
- actor
- action_type
- inputs_hash
- started_at
- completed_at
- result
- cost
- external_refs
- provenance_chain
- previous_receipt_hash
- receipt_hash

### Outcome
- outcome_id
- opportunity_id
- actual_purchase_cost
- actual_materials
- actual_travel
- actual_hours
- actual_sale_or_job_revenue
- actual_net
- days_to_cash
- result
- lessons

---

## Receipt / provenance rule

Project-wide invariant:

> No action without a receipt. No receipt without provenance.

Implementation requirement:
- consequential state transition and receipt must commit atomically where possible
- append-only receipt/provenance tables
- no silent mutation of historical evidence
- every score/recommendation records model/formula/config version
- every external side effect uses an idempotency key
- retries must not duplicate the real-world action

---

## Security boundary

Treat every listing, message, webpage, review, email, and customer text as **untrusted data**.

They may inform the model.

They may never grant authority.

Authority comes from:
- policy
- scoped capabilities
- explicit approval
- hard spend/contact limits
- tool gateway

The agent must not hold unrestricted effector credentials.

---

## 24-hour build plan

Goal: prove one real end-to-end loop.

Build:
1. Python project scaffold.
2. Postgres container.
3. migrations for opportunity/research/scorecard/recommendation/approval/action/receipt/provenance/outcome.
4. DBOS durable workflow skeleton.
5. SourceAdapter interface.
6. one real official source collector.
7. normalizer.
8. economics scorer using Agent 03 config.
9. simple CLI/web approval queue.
10. dry-run action executor.
11. receipt/provenance enforcement.
12. crash/restart/idempotency tests.

Acceptance:
- real opportunities enter automatically
- duplicates collapse
- score is explainable
- top opportunities rank
- Michael can YES/NO/MODIFY/HOLD
- ACT is dry-run
- receipt/provenance chain is complete
- restart does not duplicate an action

---

## 72-hour usable-product plan

Add:
- 3–4 source adapters
- basic comparable-price enrichment
- configurable search profiles
- geographic/travel economics
- operator dashboard
- alert queue for high-score opportunities
- outcome entry
- daily summary
- source health status
- basic backup
- simple authentication

At this point Michael should be able to wake up and see:
- best opportunities found overnight
- why they rank
- expected economics
- what needs a decision
- what to do first

---

## Seven-day plan

Add:
- stronger dedup/image matching
- IMAP alert ingestion
- experimental Craigslist adapter
- marketing draft queue
- first website/local-SEO assets
- lead/customer entities
- attribution
- more complete governance policy
- OpenBao/secrets hardening if justified
- off-box backup
- observability
- dry-run communications
- first controlled real action only after acceptance tests pass

---

## Round-Two agent assignments

### Agent A — Core Platform
Python scaffold, DBOS, migrations, service lifecycle, tests.

### Agent B — Discovery Connectors
SourceAdapter framework + first official collectors + source health.

### Agent C — Economics
Implement formulas/config + score explanations + threshold tests.

### Agent D — State / Receipts
Canonical schema, append-only receipt/provenance, idempotency, migrations.

### Agent E — Governance
Approval/action gateway, policy checks, limits, kill-switch hooks.

### Agent F — Operator UI
Dashboard, opportunity cards, YES/NO/MODIFY/HOLD queue, status.

### Agent G — QA / Integration
Cross-lane contract tests, crash/restart tests, provenance completeness, build verification.

Marketing and communications remain research-backed but are not in the first implementation wave except as mocked adapters.

---

## Rejected / deferred alternatives

- Temporal as MVP backbone — deferred due operator burden.
- CRM as system of record — rejected.
- n8n as core orchestration — rejected.
- seven independent databases/services — rejected.
- live phone/SMS/email in first MVP — deferred.
- fully autonomous purchases/offers — rejected for initial system.
- broad scraping before official/sanctioned sources work — rejected.
- Kubernetes/k3s for the first single-box deployment — deferred.
- separate vector DB/broker before scale requires it — deferred.

---

## Remaining owner decisions

Only decisions that materially affect business policy belong to Michael.

See `docs/status/MICHAEL_DECISIONS.md`.

Technical choices that are reversible should not interrupt Michael.
