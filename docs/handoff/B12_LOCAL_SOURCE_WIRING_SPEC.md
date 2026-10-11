# B-12 local-source readiness: what is connected, what is missing, exact wiring (Agent 01, 2026-10-11T21:36:13Z)
Part of the existing B-12 row; NOT a second source task. Provenance: FACT = read/observed this session; UNKNOWN = not observed.

## Connected-source coverage today (FACT)
| Source | Status | Evidence |
|---|---|---|
| GSA Auctions | **CONNECTED (cached file only)**, 153 in-scope lots, cache fetched 2026-10-11 02:48 UTC, labelled STALE | live :8766 page; `market_search.load_gsa` over `GsaLiveAdapter(path, live=False)` |
| GovDeals, Public Surplus | **NOT CONNECTED.** Adapter + parser built (lane 02 B-06, `src/mbos_discovery/adapters/email_alerts.py`, fixtures only); no mailbox, no alerts | no IMAP settings in any env/config on this host |
| Craigslist | **NOT CONNECTED.** No authorized retrieval path exists; not attempted | `ms.NOT_CONNECTED` shows it as not connected |
| eBay, Facebook Marketplace | **NOT CONNECTED** | same; eBay Insights approval (MICHAEL #8) and no unattended Facebook fetch remain separate |
| Owner-entered finds (F-141) | manual bridge only, NOT discovery | checklist |

## Prerequisites check (host, presence only; no secret printed, no mail read)
- No `discovery.toml` (only `config/discovery.example.toml`), no IMAP host/user/folder keys in `var/*.env`, no IMAP/mailbox variable in the environment, no `var/mail/` folder of .eml alerts on this host. => **all four prerequisites absent.**

## ONE precise NEED (only what is missing)
1. An **existing** DKIM-aware IMAP mailbox/service account to reuse (host, user) and a **dedicated alerts-only folder** (the reader fetches every message body in the folder it opens, so a general inbox is out of scope).
2. **Genuine GovDeals and/or PublicSurplus saved-search alerts** (Conway AR area) routed into that folder. Creating/changing those subscriptions is an owner/operator step.
3. The mailbox **app password** installed on this host outside GitHub, mode 0600, as env var `MBOS_IMAP_PASSWORD` (name only; Agent 01 never reads the value), plus `imap.live = true` for the one bounded smoke.
Not asked: product direction (already given), build authority, a new account/provider/subscription, any source-policy bypass. Alternative that needs no mailbox: the owner forwards real alert .eml files into `var/mail/govdeals/` (EmlDirReader); that proves parsing of genuine mail but is NOT live connection.
**Continues meanwhile:** the wiring below against fixtures clearly labelled FIXTURE; B-12 dry run. **Next check:** next wake (re-run the presence check above).

## Exact wiring needed to surface the source (lane 06 + lane 02; today the page is GSA-only)
Files (FACT from reading lane 06 @ 8524689): `operator_ui/market_search.py` (`load_gsa`, `NOT_CONNECTED`, `_card`), `operator_ui/market_routes.py:62` (loads GSA only when `source == "gsa"`), `operator_ui/market_view.py` (source select line ~211; "not connected" body line ~338; status line ~149).
1. `market_search.py`: add `load_alerts(source, path)` returning the SAME card shape as `load_gsa` from lane 02's `EmailAlertAdapter` records (title, price, url, location, fetched_at, kind, stale); remove "GovDeals"/"Public Surplus" from `NOT_CONNECTED` only when the loader reports status=connected from a real mailbox read, never because a fixture parser exists.
2. `market_routes.py`: dispatch on `q["source"]` (gsa | govdeals | publicsurplus | all); `all` merges and de-dups across sources via lane 02's Deduper.
3. `market_view.py`: per-source status line (connected/offline, as_of, age, stale) and "FIXTURE / not live" banner when the data is not from the live mailbox; keep Craigslist/eBay/Facebook in "not connected".
4. Distance: alert listings carry free-text location; use the existing gazetteer path, show "distance unknown, not counted as local" when unresolved (same rule as GSA).
Acceptance (all required): (a) focused tests: card shape parity with GSA, not-connected stays not-connected without a live read, FIXTURE banner on fixture data; (b) one **genuine** Conway-area alert listing from the dedicated mailbox appears via /market with source link, price, location/distance and freshness, with DKIM verified and `\Seen` unchanged (privacy-safe receipt, scrubbed fixtures); (c) real-Chrome desktop+mobile screenshots; (d) the Search Now / filter behaviour of F-142 unchanged (`tools/f142_live_check.py`).
Not claimable without (b): "connected", "live", or any Craigslist coverage.
