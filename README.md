# michael-business-os
Persistent self-hosted AI business operating system for opportunity discovery, deal scoring, marketing, CRM, communications, approvals, receipts, and revenue optimization.

## Agent 02 — discovery lane (branch `research/agent-02-opportunity`)
Read-only DISCOVER + NORMALIZE implementation: `src/mbos_discovery`. See
`docs/implementation/agent-02-discovery-lane.md`. Quick start:

    python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/python -m pytest -q
    .venv/bin/mbos-discover run --config config/discovery.example.toml --fixtures tests/fixtures
