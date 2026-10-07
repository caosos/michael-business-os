# Decision

Status: PROPOSED

## Context
Marketing needs a CRM to hold the canonical lead/contact record with attribution source carried through to closed revenue (closed-loop), plus a referral-partner segment. CRM/business-state is **Agent 04's domain**, so this is explicitly a cross-agent decision: marketing and CRM must converge on ONE CRM and a shared contact/lead schema, or attribution and state will diverge.

## Options considered
- **Twenty** — AGPL-3.0, ~52–58k★, modern TypeScript + PostgreSQL, fast-growing, REST/GraphQL API + webhooks. Good for a small, growth-oriented service business. **[FACT]**
- **EspoCRM** — AGPL-3.0, lightweight PHP, runs in <400MB RAM, quick to stand up. Strong lean-SMB fit. **[FACT]**
- **Odoo Community** — LGPL-3.0; CRM is basic but part of a full ERP (invoicing, inventory, **field-service dispatch/scheduling**) — compelling if Michael wants quoting + dispatch in one system. **[FACT]**
- **SuiteCRM** — AGPL-3.0, full Salesforce-style suite, heavier to run. **[FACT]**

## Recommendation
From a marketing standpoint, **Twenty** (modern, API-first, scales to a team) or **EspoCRM** (leanest to operate solo). **Odoo CE** becomes the stronger pick if the wider OS wants invoicing + field-service dispatch unified with CRM — a decision that belongs to Agent 04 + Agent 01, not marketing alone. Marketing's hard requirement is only: a single CRM with an API/webhooks and a lead record that can store the attribution object (utm/gclid/first-touch/self-reported-source → revenue).

## Evidence
- twenty.com / github.com/twentyhq/twenty (AGPL-3.0).
- espocrm.com (AGPL-3.0); odoo.com (LGPL-3.0); suitecrm.com (AGPL-3.0).
- Attribution object spec: `docs/research/agent-07-marketing.md` §13.
- Receipt: `docs/receipts/2026-10-06-marketing-research.md`.

## Risks
- **Divergence with Agent 04** if each picks a different CRM → duplicate/contradictory state. This ADR exists to force reconciliation.
- Twenty is young (feature gaps vs mature CRMs); EspoCRM UX is dated; Odoo is heavier to run.
- AGPL copyleft only matters if we redistribute/offer a modified hosted version — not an issue for internal use. **[FACT]**

## Reversibility
Low-to-moderate once real data accumulates — CRM migrations are painful. Decide early and jointly. Keeping the attribution schema tool-agnostic (documented separately) reduces lock-in.

## Coordinator review required: YES
