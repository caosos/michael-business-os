# Receipt: A-74 ADR-0015 accounts + location-scoped sources (docs only)

- Actor: Agent 04 State. DRY-RUN. No code, DDL, credential, message, spend or contact.
- Output: `docs/decisions/ADR-0015-accounts-and-location-scoped-sources.md`, status PROPOSED (Agent 01 accepts and queues rows P-74-1..8, which are written as text inside the ADR).
- Provenance (FACT): owner direction quoted in queue row A-74; `docs/handoff/B12_CRAIGSLIST_FACEBOOK_SOURCE_STATUS.md` (alert-email-only Craigslist; FB/OfferUp not readable); `state/prefs.json` shape from `docs/receipts/f59-save-restart-proof/scenario-A/state/prefs.json` on `origin/research/agent-01-coordinator`; migrations 0001-0028 in this branch; ADR numbering: highest existing is ADR-0014.
- Frozen contracts v1.0.0: not touched.
- Health: `cd state && .venv/bin/python -m pytest` -> 330 passed, 1 skipped, 0 failed (the skip needs MBOS_ECONOMICS_SRC).
- Owner questions: who gets accounts (default invite-only member role); which regions beyond Arkansas (default none).
