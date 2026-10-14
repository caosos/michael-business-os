# DealSniffer — handoff to a Claude session on the Linode (resume token `DS-A01-20261014-LINODE`)

From Oct 14, 2026 the Linode (dealsniffers.com) is where DealSniffer work continues. The EliteDesk stays a development copy only.
You are **Agent 01 (DealSniffer coordinator)** for Michael. Read this whole file before you do anything.

## Hard rules (owner direction — never relax these)
1. **Do not touch CAOSCare or Cutler Lawns** on this server: not their files, services, databases (MongoDB 27017), ports (3000, 8000,
   8001) or nginx blocks. DealSniffer has only its own paths (below), each carrying a `DealSniffer-managed` marker.
2. **Secrets are typed by Michael on the server only.** Never print, log, commit or ask for their values in chat: `/etc/dealsniffer/oauth.env`,
   `/etc/dealsniffer/alerts.env`, `/etc/dealsniffer/gsa.key`. Name a file or a variable, never its value.
3. **No paid listing providers.** No Bright Data, no paid feeds, no new billing (owner, Oct 13). Paid requests are denied in code.
4. **Never scrape** Craigslist, Facebook, HiBid or Proxibid. Craigslist reaches DealSniffer **only** through its own saved-search alert
   e-mails to **dealsniffer2026@gmail.com**. Never use Michael's personal Gmail for anything DealSniffer.
5. **Stale Facebook listings are never shown** (owner, Oct 14). `operator_ui/market_facebook.py: SHOW_HISTORICAL = False`.
6. **Property/Land is opt-in**: "All categories" excludes Land/Real Estate unless Land is ticked.
7. Account creation, passwords, CAPTCHAs, Google account choice/consent, accepting terms: **Michael does those**. Ask before any change to
   security settings, persistent credentials, firewall, nginx outside DealSniffer's own site file, or anything that is hard to undo.
8. Do not copy private EliteDesk data (owner profiles, bids, hidden lists, mailbox credentials) to this server.
9. This is a **limited owner/test deployment**. Do not call it production until backups, restore, recovery and multi-user persistence
   are tested. Do not claim a deployment from code or CI alone: show the server's own output.
10. Michael's terminal wraps long lines and breaks them: give him short command lines, one block at a time. Wait ~5 s after a restart
    before `verify.sh`.

## What is on this server
| Piece | Where |
|---|---|
| Repo checkout (detached at a pinned commit) | `/home/michael-chambers/dealsniffer/repo` (github.com/caosos/michael-business-os) |
| Install package | `deploy/linode/` on branch `research/agent-01-coordinator` (this file) |
| Code, one dir per pinned release | `/opt/dealsniffer/releases/<id>`; active = `/opt/dealsniffer/current`, previous = `/opt/dealsniffer/previous` |
| Data (accounts, prefs, caches incl. `cache/alert-mail.json`) | `/var/lib/dealsniffer` (user `dealsniffer`) |
| Settings / secrets | `/etc/dealsniffer/{dealsniffer.env, oauth.env, alerts.env?, gsa.key?}` (root:dealsniffer 640) |
| App service | `dealsniffer.service`, `127.0.0.1:8765`, logs `journalctl -u dealsniffer` |
| Hourly listings refresh | `dealsniffer-refresh.timer` → `refresh.py` (GSA official API, auctioneers' own event pages, alert e-mails) |
| Public site | nginx `sites-available/dealsniffers.com`, Let's Encrypt certificate, `https://dealsniffers.com` |

Public mode (`MBOS_PUBLIC_DEPLOYMENT=1`): Google sign-in required, no local owner, unknown/loopback Host → 403, operator pages closed,
saved searches off. Google sign-in works (Michael signed in Oct 14).

## Pins in `components.env` (package commit after this file)
UI lane 06 `6eec11b` · lane 02 discovery `8e4bb4c` · mbos `50c2bca` · economics `4bc91f3` · lock `683b1d22fdd5`.
Branches: lane 06 = `research/agent-06-communications`, lane 02 = `research/agent-02-opportunity`, coordinator = `research/agent-01-coordinator`.

## Craigslist (the source Michael wants most)
* Craigslist account **dealsniffer2026@gmail.com** has 6 Little Rock for-sale saved searches with e-mail alerts ON: trailer, utility trailer,
  log splitter, outboard, mower, tools. (A stray "trailer" search with alerts OFF exists on Michael's personal Craigslist account; he
  deletes it himself.)
* Genuine alert format (seen Oct 14): sender `alerts@alerts.craigslist.org`; Gmail writes `dkim=pass header.i=@alerts.craigslist.org`;
  listing links `https://www.craigslist.org/view/d/<town-title>/<opaque id>`; the area only in the "view all" link
  (`/search/area/littlerock`); some text double-encoded by Craigslist; thumbnails on images.craigslist.org. Parser: lane 02
  `src/mbos_discovery/adapters/email_alerts.py`; cards: lane 06 `operator_ui/market_sources.py` (`_card`, `_town`, `_THUMB`).
* On the EliteDesk with the same code: 95 listings, 80 with photos; from 72032: 7 within 10 mi, 27 within 25, 56 within 50, 77 within 100.
* On this server Craigslist needs `sudo bash deploy/linode/configure_alerts.sh` (Michael types the Gmail **app password**, hidden). The
  refresh then reads the mailbox read-only once an hour.

## First things to do here (in order, each only after the previous one is proven by command output)
1. Confirm what is running: `readlink /opt/dealsniffer/current`, `systemctl status dealsniffer dealsniffer-refresh.timer --no-pager`,
   `journalctl -u dealsniffer-refresh -n 20 --no-pager`, `bash deploy/linode/verify.sh --public | tail -3`.
2. If `current` is not the `ui-6eec11b02b63…disc-8e4bb4c4ac5a…` release: `git fetch origin`, check out the package commit named in the
   resume message, `sudo bash deploy/linode/install.sh`, `sudo systemctl restart dealsniffer`, wait 5 s, `verify.sh --public`.
3. Alerts mailbox: if `/etc/dealsniffer/alerts.env` is absent, ask Michael to run `configure_alerts.sh` himself. Then
   `sudo systemctl start dealsniffer-refresh.service` and read the journal: `alert_mail` should say `ok` with `kept_from_alert_senders`.
4. Prove listings on the public site in a browser after Michael signs in: Craigslist only and All sources at 10/25/50/100 mi from 72032;
   original links, prices, towns, distances, photos; no Facebook cards; no Land unless ticked.
5. Optional, owner decides: link Michael's Google address as owner (`configure_secrets.sh --replace`, he types it); a free GSA key in
   `/etc/dealsniffer/gsa.key` (see README).

## Next build (owner asked Oct 14: "the software will have to do the same thing and have an engine for this to work")
Every user must get local Craigslist (and other alert-based) listings without anyone clicking around for them:
* Per-account alert address (plus-addressing on the dedicated mailbox, e.g. `dealsniffer2026+<account>@gmail.com`), routed to that
  account only (lane 02 has per-user alert groundwork, B-40).
* For the user's town, radius and categories, DealSniffer generates the right Craigslist region(s) and saved-search links; the user
  clicks "save search" and turns alerts on with their alert address. Craigslist's terms forbid software creating accounts or saved
  searches, so that click stays the user's.
* Per-account listings, isolation tests, and the same flow for GovDeals / Public Surplus alerts.

## How to change code
Work in the repo on the right lane branch, run that lane's tests, commit with
`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, push, then pin the new commit in `components.env` and reinstall. Pushing from
this server needs GitHub credentials that Michael chooses to set up; until then, describe the change and ask.
Lane 06 has ~80 long-standing test failures (baseline); judge a change by "no new failures", not by a green suite.

## Not proven yet
Backups and restore of `/var/lib/dealsniffer`; recovery after host loss; concurrent multi-user persistence; per-account saved searches;
real Craigslist alerts read **on this server**.
