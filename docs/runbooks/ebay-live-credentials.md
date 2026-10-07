# Runbook — eBay Browse API live credentials

Status: **no credentials in this environment** (FACT, 2026-10-07: no `EBAY_*` variables set).
The adapter runs from recorded fixtures until these steps are done. Nothing below involves
buying, bidding or contacting anyone: the Browse API is read-only search, and the transport
refuses every other eBay endpoint.

## Steps (Michael or Aria; ~15 minutes, free)
1. Create or sign in to an eBay developer account at developer.ebay.com (Michael's own account).
2. Application Keys → create a **Production** keyset. (Sandbox works for wiring checks but returns test data.)
3. If prompted, complete the marketplace-account-deletion notification opt-out/endpoint step for the keyset (eBay requirement for production keys; UNKNOWN whether it is required for Browse-only apps in 2026).
4. Copy **App ID (Client ID)** and **Cert ID (Client Secret)**.
5. Store them as secrets — not in git. Wave one: a `0600` env file outside the repo, e.g. `~/.config/mbos/ebay.env`:
   ```
   EBAY_CLIENT_ID=...
   EBAY_CLIENT_SECRET=...
   EBAY_ENV=production
   ```
   Later: OpenBao (ADR-0005 stack) with a lease for the discovery agent only.
6. Smoke test: `set -a; . ~/.config/mbos/ebay.env; set +a; .venv/bin/mbos-discover run --config config/discovery.example.toml`
   Expect `ebay ... ok fetched=N`. On `auth` → re-check the keys. On `blocked`/`rate_limited` twice → the source FREEZES; investigate before `clear-freeze`.

## Quota
Default Browse quota is ~5,000 calls/day (Round One research, FACT at the time). The example config uses
5 keywords × ≤2 pages = ≤10 calls + 1 token per run → a 30-minute cadence is ≈ 530 calls/day.

## Verify on first live call (UNKNOWN until then)
- Filter names `pickupPostalCode`, `pickupRadius`, `pickupRadiusUnit`, `deliveryOptions:{SELLER_ARRANGED_LOCAL_PICKUP}`, `conditions:{USED}` are accepted as written.
- `distanceFromPickupLocation` is returned in summaries when pickup filters are set.
- Real field shapes match `tests/fixtures/ebay/*.json` (fixtures are hand-built from the documented schema, not recorded live).
If any differ, record a live response as a new fixture and adjust the mapping + tests together.
