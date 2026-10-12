# Decision

ADR-0015 — User accounts, per-user preferences, and location-scoped sources

Status:
PROPOSED

(Drafted by lane 04 for task A-74. Not self-accepted: Agent 01 accepts and queues the migration rows below. No implementation is part of this row.)

Date: 2026-10-12
Author: Agent 04 (State)

## Context

Owner direction, 2026-10-12 ~14:30 CDT: the marketplace page must do everything GSA Auctions' search and listing experience does, and also cover Facebook Marketplace, Craigslist and other apps selling things. It is tailored to Arkansas now. Eventually whoever logs in searches wherever they are, with the local sources for that place.

Repo truth today (FACT, from the coordinator branch):
- One owner. Page preferences are a single `state/prefs.json` (`saved`, `dismissed`, `more`, `less`, `last` with `base`, `radius`, `source`, `cat`, `view`). The base is a free-text place (`Conway AR`) and the radius is 150 mi.
- Sources are hard-wired adapters. Only GSA is connected. Craigslist is reachable only as the owner's own official saved-search alert e-mails through the read-only B-06/B-12 mailbox seam. Facebook Marketplace and OfferUp are not readable (`docs/handoff/B12_CRAIGSLIST_FACEBOOK_SOURCE_STATUS.md`).
- The spine (lane 04) has owner-only paths gated by the `owner_channel` role (D-24/D-25/D-28..D-31), and a watchlist with bid-ceiling storage and no bid path (D-33, migration 0028). None of these rows carries a user id.

The problem: a second person logging in would share the owner's saved items, dismissals, location, capital and mailbox. Sources would also be shown that mean nothing where that person lives (an Arkansas Craigslist feed for someone in Ohio).

## Decision

### 1. Accounts: a small, local, invite-only user table
- New `mbos.app_user` (`user_id` ULID with `usr_` prefix, handle unique, display_name, role, home_zip, home_state, home_lat, home_lng, default_radius_mi, tz, status, created_at). `role` is `owner` or `member`. Exactly one `owner` exists (the current Michael login), seeded by migration; it is never created through the UI.
- Authentication is a local login (scrypt or argon2id password hash, or WebAuthn passkey later) with a server-side session cookie, served over loopback/tailnet only. No external identity provider, no sign-up page: the owner invites a member by creating a row. `[REC]` Passwords are never stored in Postgres in plaintext, and never appear in receipts or logs.
- **Authority does not widen.** `member` is read, search, save, dismiss and watch only. All money, mission, capital, approvals, bid ceilings, PANIC release, `record_*` human-input paths and every outward action stay owner-only (existing `owner_channel` gate). A member's session never holds `owner_channel`, `approver`, or any effector role. Members cannot create ActionRequests. Bidding stays impossible for everyone (D-33 stands).
- Every receipt for a user-visible write carries `actor = usr_...` so provenance names who did it. The hash chain and receipt format do not change (`actor` is already a free string; `Receipt.details` is canonical JSON per ADR-0010). **No frozen contract in `docs/research/contracts` v1.0.0 is touched.**

### 2. Per-user preferences replace the single prefs file
- New `mbos.user_pref(user_id, key, value jsonb, updated_at)`, primary key `(user_id, key)`. Keys mirror today's file: `saved`, `dismissed`, `more`, `less`, `last`, `enabled`. Writes go through one function `mbos.set_user_pref(...)` that accepts only the caller's own user id.
- Migration of the existing file: a one-time import of `prefs.json` into the owner's rows, idempotent and receipted. The file stays as a read fallback for one release, then is removed.
- Saved and dismissed move from "item-level flags" to **per-user state** (`mbos.user_item_state(user_id, item_id, state, at)`). Items themselves remain shared public facts. One user's dismissal never hides an item for another.
- Watchlist and alerts (D-33 tables) gain a `user_id`. Alerts fire once **per user per item per threshold**. Bid-ceiling storage stays owner-only.

### 3. Each source declares a coverage region
New registry `mbos.source_registry` (seeded from a versioned JSON file, `config/sources.v1.json`, reviewed like policy):

| Field | Meaning |
|---|---|
| `source_id` | `gsa`, `ebay`, `craigslist`, `govdeals`, `publicsurplus`, `fb_marketplace`, `offerup`, local auction houses |
| `coverage.scope` | `national`, `states`, `metro`, or `point` |
| `coverage.states` | list of USPS codes (e.g. a regional auction house = `["AR","OK"]`) |
| `coverage.center`, `coverage.radius_mi` | for `metro` and `point` sources (a single yard) |
| `coverage.subdomain` | Craigslist region slug (`littlerock`, `fayar`, ...) |
| `access_mode` | `api`, `alert_email`, `manual`, `excluded` |
| `policy_ref` / `terms_checked_at` | the primary terms document and date |
| `status` | `connected`, `fixture`, `not_connected`, `blocked` |

- Examples: GSA and eBay are `national` and `api`. Craigslist is `metro` per subdomain, `alert_email`. Facebook Marketplace and OfferUp are listed with `access_mode: manual` / `status: blocked` and the existing no-unattended-fetch ruling. They are visible in the UI as "not connected" with the reason, never silently absent. Adding a source is a registry row plus its adapter. No source is added whose terms forbid the access mode.
- Coverage is data, not code, so "tailor to Arkansas" is just the owner's seeded registry rows and prefs. It is not a fork.

### 4. Choosing sources and radius from the user's place
1. The user's location is a ZIP (or a typed place that resolves to one) set in their profile. Resolution is an **offline** ZIP table (Census ZCTA centroids, public domain, shipped in the repo). No geocoding service is called, so no user location leaves the box. `[REC]`
2. A source is **active** for a user if its scope is `national`, or the user's `home_state` is in `coverage.states`, or the great-circle distance from the user's coordinates to `coverage.center` is within `radius_mi + user radius`. The page lists active sources first and can show inactive ones under "not near you".
3. **Radius default** comes from the profile: `default_radius_mi` if set, else 100 mi for `metro` and `point` sources, and the user's search radius is applied as a pickup-distance filter for national sources (GSA/eBay items carry a location). The owner row is seeded `home_zip` Conway AR 72032, `home_state` AR, `default_radius_mi` 150, matching today's behavior, so **Arkansas remains the default for this owner** and nothing changes for them on day one.
4. A per-search override (the existing `last.base` / `last.radius`) still wins over the profile default for that request.

### 5. Alert e-mail sources, per user
Craigslist's supported route is each person's own official saved-search alert e-mail. We do not scrape. With several users this needs care:
- One dedicated, read-only alerts mailbox/folder (existing B-06/B-12 seam, `\Seen` never changed) receives all users' alerts. Each user registers their alert address as a **plus-address alias** of that mailbox (`alerts+<handle>@...`). The ingestor resolves the `To:` plus tag to `user_id`.
- A message with an unknown or missing tag is **quarantined** (counted, not parsed into any user's feed) and shown to the owner only.
- Parsed listings are stored once as shared public facts (stable ID, original URL, title, price, location), plus a per-user row `mbos.user_item_interest(user_id, item_id, source_id, received_at)`. The user sees only listings from their own alerts. Mail bodies and addresses are never exposed to other users.
- Each member sets up their own Craigslist account and saved searches (their own terms acceptance, their own alerts). The owner never configures a member's Craigslist account. `[REC]`
- Alert state per source for a user is shown honestly: `no alert received yet` / `last received <time>` / `stale`.

### 6. What does not change
- Hash-chained receipts, frozen contracts, `owner_channel` gating, PANIC, DRY-RUN everywhere, no bid path, human-only capital and mission.
- Capital, bankroll and weekly mission remain the owner's, per ADR-0013. A member has no bankroll in this ADR. A per-user capital ledger is out of scope.

## Options considered
1. **Keep one owner, add a "location" field** (rejected). It fixes source choice for one person but still shares saved/dismissed state and a mailbox, and does not allow anyone else to log in.
2. **Full multi-tenant (a schema or database per user)** (rejected). Overkill for a self-hosted, invite-only box. Items are public facts that dedupe well when shared.
3. **External IdP (OIDC/SSO)** (deferred). Adds a hosted dependency and secrets to a loopback box. Revisit if the page is ever exposed beyond the tailnet.
4. **Shared items + per-user state + coverage-tagged sources + local ZIP resolution** (CHOSEN).

## Consequences
- Positive: a second person gets a correct, private, local-first page without touching owner authority. Source coverage becomes inspectable data. Location stays on the box.
- Cost: one new auth surface to harden (session fixation, lockout, CSRF on a stdlib UI), and an ongoing ZIP table.
- Risk: a member misusing the shared alerts mailbox plus-tag. Mitigation: quarantine unknown tags, owner-only mailbox settings.
- Risk: API-key quotas (GSA `DEMO_KEY`, eBay) are shared across users. Mitigation: the existing hourly-at-most cached refresh is per-source, not per-user, so N users do not multiply upstream calls.

## Owner questions (consolidated; smallest boundary)
1. **Who gets accounts?** Recommended default: invite-only, created by the owner, `member` role, no money or approval authority. Blocks: P-74-1 onward going live for anyone but the owner. Does not block: the registry, ZIP table, and owner-only changes.
2. **Which new regions matter first** (to seed registry rows beyond Arkansas)? Recommended: none until a real second user exists. Arkansas is the only seeded region.

## Migration rows (proposed text; Agent 01 queues)
Proposed IDs use `P-74-n`. Agent 01 renumbers them into the normal sequence.

| ID | Lane | Pri | Task | Deps | Acceptance |
|---|---|---|---|---|---|
| P-74-1 | 04 | P1 | Migration 0029: `mbos.app_user`, roles, seed the owner row (Conway AR 72032, AR, 150 mi). Members get no `owner_channel`/approver/effector. Tests include a member session being refused on every owner-only function (D-24/25/28..31 and D-33 ceiling). | ADR-0015 accepted | Spine suite green; a new test proves a member cannot reach any owner path. |
| P-74-2 | 04 | P1 | Migration 0030: `mbos.user_pref`, `user_item_state`, `set_user_pref`; add `user_id` to the D-33 watch/alert tables (alerts once per user per item per threshold); backfill to owner. | P-74-1 | Two users' saved/dismissed/watch never leak; D-33 tests still pass; the receipt chain verifies. |
| P-74-3 | 04 | P1 | Migration 0031: `mbos.source_registry` and `user_item_interest`, plus a seed loader for `config/sources.v1.json` (GSA/eBay national, Craigslist per-subdomain metro, GovDeals/PublicSurplus alert_email, FB/OfferUp blocked/manual). | P-74-1 | Registry rows validate against a JSON schema; each row has a `policy_ref`. |
| P-74-4 | 02 | P1 | Offline ZIP table (Census ZCTA centroids) and `sources_for(user)` / default-radius function with unit tests (national always on; state match; distance match; Arkansas owner unchanged). | P-74-3 | Test matrix incl. an Ohio user sees no Arkansas Craigslist; owner output identical to today. |
| P-74-5 | 06 | P1 | UI: login/session (local auth, CSRF, lockout), per-user prefs read/write, profile ZIP/radius, sources-near-you list with "not connected: reason" for blocked sources. One-time import of `state/prefs.json` to the owner row. | P-74-1, P-74-2, P-74-4 | Owner sees the same page as before; a second invited user sees their own state; browser check by Agent 01. |
| P-74-6 | 02 | P1 | Per-user alert-mail ingest: plus-tag to user, quarantine for unknown tags, per-user interest rows; shared listing facts deduped. Fixture-first, read-only `\Seen` unchanged. | P-74-2, P-74-3 | Fixtures with two users' alerts produce disjoint feeds; an untagged message is quarantined and shown to the owner only. |
| P-74-7 | 05 | P2 | Governance review: member role cannot obtain any owner/approver/effector/PANIC authority; session and password handling checklist. | P-74-1, P-74-5 | Written review receipt with pass/fail per control. |
| P-74-8 | 01 | P2 | Docs: member onboarding runbook (invite, set ZIP, set up own Craigslist saved search with the plus address). | P-74-5, P-74-6 | Runbook reviewed. |

## Assumptions and unknowns
- `[INFER]` The box stays on loopback/tailnet. If it is ever exposed publicly, ADR needed for IdP, rate-limiting and TLS.
- `[UNK]` Whether a plus-addressed alias is accepted by Craigslist's alert sign-up for the chosen mail provider. If not, the fallback is one folder or alias per user, with the same quarantine rule. Verify at P-74-6 with one real alert.
- `[UNK]` Whether Facebook Marketplace or OfferUp ever get a lawful readable route. They stay registry rows with `status: blocked` until then (B-12 ruling stands).
