# Decision

ADR-0007 — Business scope: value-add FLIPS and paid SERVICES under one OS

Status: ACCEPTED (2026-10-06). **Decided by Michael** (clarification received by Agent 01 on 2026-10-06), recorded by Agent 01.

## Context
The specialists assumed different businesses:
- 02 and 03: equipment flips and service jobs.
- 06: used cars.
- 07: home services only, which it said was "confirmed with Michael".

The Item schema and the MVP need a single answer.

## Decision (Michael's words, preserved)
The Business OS serves **BOTH** lanes. Neither one narrows the system.

**1. Value-add flips:**
- trailers, mowers, generators, welders, compressors, tools
- commercial and mechanical equipment
- project vehicles, when economically attractive
- other undervalued assets Michael can repair, fabricate or improve and resell

**2. Paid services:**
- mobile repair, equipment repair, drywall repair
- assembly, handyman and small repairs
- smart-home installation
- related technical and mechanical services

> "Used cars are only ONE possible flip category. Home services are only ONE revenue lane. Do NOT narrow the operating system to cars. Do NOT narrow it to home services. The canonical Item/Opportunity model must support both flips and service jobs under one system with type-specific fields."

## Consequences
- Item v1 (ADR-0004) has `type ∈ {flip, service}`, a per-type `category` enum, and per-type `economics` blocks (03's schemas).
  - **Flip categories:** `trailer`, `mower`, `generator`, `welder`, `compressor`, `tool`, `commercial_equipment`, `mechanical_equipment`, `project_vehicle`, `other_asset`.
  - **Service categories:** `mobile_repair`, `equipment_repair`, `drywall_repair`, `assembly`, `handyman`, `smart_home_install`, `technical_service`, `mechanical_service`, `other_service`.
  - `subcategory` holds detail. Adding a category needs a minor version bump, not a new type.
- **02:** collectors cover both lanes (marketplaces and auctions for flips; lead sources for services).
- **03:** the flip and service weight vectors both stay first-class.
- **06:** generalizes from cars. Car flows become the `project_vehicle` instance.
- **07:** marketing covers service-lead generation *and* resale listings for flips (the manual-assist lane for Marketplace and Craigslist postings).
- The MVP slice is one flip vertical, and the 1-week path adds one service vertical, so both lanes are proven inside week one.

Reversibility: High (enum additions). Coordinator review required: NO (Michael decision).
