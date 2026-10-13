# Agent 01 (DealSniffer coordinator) close-out — 2026-10-12 ~19:50 CDT

The owner closed this session. Nothing is running on Agent 01's behalf. The watchdog (tmux `mbos-watchdog`) is the owner's standing service and was left running as it was.

**Continue token:** `DS-A01-20261012-CLOSEOUT`. A new session that is given this token should read this file first, then `docs/handoff/AGENT01_RESUME.md` and `docs/status/READY_QUEUE.md`.

## State

- **Live UI (8766):** lane 06 `fb84d0c` (F-163/F-164/F-165 search page and detail page).
- **Accepted but NOT released:** F-161 (alert-mail listings for GovDeals, Public Surplus and Craigslist on /market).
  - Lane 06 `dc0e804` with lane 02 `62a1bb0`. It passed `reload_ui.sh --verify-only` on staging.
  - The owner runs:
    `tools/release_marketplace.sh dc0e804 62a1bb095edb694c693f5b648e48d48d842cd4b5`
  - The lane 02 SHA must stay `62a1bb0` or later. Older lane 02 lacks the `craigslist_email` origin, which gives 17 failures.
- **Greyed sources on /market:** greying is by design. A source with no listings is disabled.
  - GovDeals, Public Surplus and Craigslist light up only after two things:
    1. the F-161 release;
    2. real alert e-mails arriving in dealsniffer2026@gmail.com.
  - HiBid website and OfferUp stay blocked by their terms. eBay is deprioritised by the owner.
- **Alert mailbox:** dealsniffer2026@gmail.com.
  - The app password is in `~/.config/mbos/imap.env` (mode 600) and the config in `~/.config/mbos/discovery-alerts.toml`. The login works.
  - The watchdog starts `refresh_alert_mail.py --live` hourly (commit 1edd604). It only does anything once F-161 is live.
  - NEVER use the owner's personal Gmail.
- **Not done: alert sign-ups.**
  - Gmail label `DealSniffer/Alerts` plus a filter for govdeals.com, publicsurplus.com, craigslist.org and auctionzip.com.
  - GovDeals saved searches, the Public Surplus interest list, Craigslist saved searches in 4 AR regions, and AuctionZip follows.
  - The proposed list is in the session transcript. The owner did not approve it yet.
  - The owner does account creation, passwords and CAPTCHAs. Each save needs his OK.
- **Facebook (B-44, BLOCKED):**
  - The Bright Data token on the host returns HTTP 200.
  - Worker commits: lane 02 `5bca3a1` (202+poll support, 453 passed) and `83274d0` (status). **Not reviewed by Agent 01.**
  - One paid live smoke returned 20 records with no error. A script bug lost the field, radius and listing_date counts, so registry `fb_marketplace` stays `fixture`.
  - Next steps:
    1. Get the owner's OK for ONE more bounded run (`tools/b44_live_smoke.py`, counts only).
    2. Review.
    3. A lane 06 release to make Facebook selectable.
- **Open rows:** F-162 (login UI), G-24, A-75 (ADR-0015 follow-ups); A-73 (watchdog wake for finished workers).

## Cleaned up

- Review worktrees `../review-f159` and `../review-l02` removed. Staging port 8791 is free.
- The 8790 stage server (`var/stage/bbc80ec…`) was NOT started by this session and was left alone.
