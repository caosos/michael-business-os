# Deal Sniffer: consolidated status and the smallest remaining owner decision

Agent 01, 2026-10-10 ~07:56Z (for ARYA-20261010-0741). Facts below were observed on the host or computed from the cited commits.

## What is live (unchanged since 02:04Z)
`mbos-dev-ui` :8766 serves the **F-48** export. Marketplace landing and real GSA listings are live; F-49 to F-59 are **not** live (no min/max price, no browse-first gallery, rounded radius, fictional TV still on `/mission` `/summary` `/digest` `/ledger`, saved searches drop their focus terms).

## What is built and verified on staging (final head `2897374`, lane 06; coordinator head contains the safety tooling)
- F-49 to F-59: live-only pages, local ZIP/city gazetteer, strict price/radius with exact (unrounded) distance, validation messages, unknown results kept out of the checked set, browse-first gallery with category rows, wide-screen density, saved searches that keep categories, condition, row order and any-of focus terms, honest login-gated photo tiles, stale-cache warning.
- Evidence: canonical matrix **40 PASS / 6 PARTIAL / 0 FAIL / 0 NOT RUN** (`docs/handoff/F-51-F-52-acceptance-matrix.md`); Agent 01's own real-Chrome proofs (`docs/receipts/f57-*`, `f59-save-restart-proof`); listing IDs and links compared with the cache.
- Gates (Agent 01, 07:44-07:52Z, resale file included): reference **383 passed / 1 failed** (`test_resale_f39` socket timeout in a full run; passes alone 4/4, unresolved), lane D+E **105 passed / 2 failed** (known F-32 pair). Not all green.
- **Not proven:** anything on the live database (saved-search Save needs the owner's PIN); B16 (Back/Forward changes the result set; both tested searches returned the same five IDs); B12 external click (none by design); five-across everywhere, phone first card needs scrolling (B01/B03/C08 PARTIAL); photos stay login-gated tiles; persistence evidence is a STUB decision store with real files and a real process restart.

## The prepared reload (not executed)
`docs/handoff/LIVE_RELOAD_PACKET_8766.md` and `tools/reload_ui.sh 28973742511834201175010c6521a678a7519da6`: verified backup and export before anything is stopped, artifact tree-hash identity plus semantic page checks, automatic rollback judged against the old UI's baseline (never accepting HTTP 500 or 000), any failure after the stop goes through rollback, 13 isolated failure-injection tests. Identity limit: on-disk hash + marker + restart + route markers, not a SHA returned by the running process. About 11 s downtime, only `mbos-dev-ui`.

## Infrastructure state (observed)
Pickup watcher `mbos-pickup` (zero-model, heartbeat + ACK; model executor only for instructions) running; dispatcher `mbos-dispatcher` running the current code, idle, queue warnings logged for 3 legacy rows; no worker running; quota session 58% / week 15% (guard allows runs, included allowance only). Not installed: systemd unit (prepared in `ops/systemd/`), no linger. Desktop-Agent and CAOSCare untouched.

## Remaining owner decisions (smallest first)
1. **Approve, or not, ONE UI-only reload of `mbos-dev-ui` to `2897374`** with `tools/reload_ui.sh`. Until then the owner sees the F-48 screen, and the work above is invisible. After it: the owner clicks Save with the PIN on the live page (the one check Agent 01 cannot do), and Agent 01 runs `--verify-only 8766`.
2. Optional: cache refresh. The cache is from 2026-10-10T00:19Z; the only supported route is lane 02's live GSA adapter (public DEMO_KEY, one fetch per hour); no wrapper script exists yet.
3. Optional: systemd install so the pickup watcher survives a reboot (`docs/operations/PICKUP_PERSISTENCE.md`).
4. Real sourcing beyond GSA is blocked on owner decisions (B-12 live source credentials, GovDeals/PublicSurplus terms); Craigslist and Facebook Marketplace stay out (terms).

## Checkpoint
No independent approved work remains for Agent 01 except low-value P2 A-50 (a ResearchWatcher edge case; not started, deliberately: it does not move real sourcing or income). Nothing runs that spends model allowance while idle. Agent 01 resumes on a new instruction, the owner's reload approval, or a failed check.
