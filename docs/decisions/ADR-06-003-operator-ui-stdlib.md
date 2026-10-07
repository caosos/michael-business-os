# Decision

ADR-06-003: Operator UI wave one is a stdlib-only, server-rendered local web app

Status: PROPOSED (Agent 06). Only Agent 01 marks this ACCEPTED.

## Context
ADR-0006 makes the Operator UI the primary approval surface. Wave one needs a minimal UI with opportunity cards and YES/NO/MODIFY/HOLD. The brief prefers "a minimal local web UI over a large framework if both satisfy the contract". FACT: the host has Python 3.10.12 with no pip, so no FastAPI/Flask/jsonschema is available without changing the host.

## Options
1. **Stdlib `http.server`, server-rendered HTML, no JS.** No dependencies, a tiny attack surface (CSP `default-src 'none'`), and it runs today.
2. FastAPI + HTMX/Jinja. Nicer ergonomics, but it needs a package install and a venv, plus more supply chain.
3. A SPA (React/Vite). Overkill for a single operator, and it adds a TS toolchain (ADR-0008 allows TS for UI only).

## Recommendation
Option 1 for wave one. Domain logic (`approvals.py`, `gateway.py`, `views.py`) is separate from HTTP, so moving to FastAPI later only replaces `server.py`. RECOMMENDATION: revisit when lane E adds WebAuthn/TOTP and remote access, which is the point where a framework's session and auth middleware starts paying for itself.

## Risks
- `http.server` is not hardened for exposure to the internet. Mitigation: it binds to loopback only and checks the Host header. Remote access goes via an SSH tunnel until lane E's auth exists.
- The SQLite stand-in store could be mistaken for the spine. Mitigation: it is labeled STAND-IN in code and docs, and lane D replaces it behind the same interface.

## Reversibility
High. HTTP is a thin layer over the domain modules.

Coordinator review required: YES (UI stack, plus two contract gaps noted in `docs/research/agent-06-operator-ui.md` §6: no `superseded` status, no `ACTION_EXPIRED` receipt type).
