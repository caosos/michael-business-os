# F-154: closing-soon badges in My bids (lane 06, DRY-RUN, display only)

- Task: F-154 (owner need 2026-10-09: he joins auctions at the end). Provenance: queue row F-154; code `operator_ui/market_bids.py` (`closing`, `badge`, sort), `market_autobids.py`, `market_routes.py`, `market_view.py`.
- Change: My bids rows get a "CLOSING WITHIN 2 H" (0 < left <= 2 h) or "CLOSING TODAY" (close falls on today's America/Chicago date, still ahead) badge and sort first (2 h, today, then the rest by close time). Same badges on auto-detected rows that are still live and on result cards of saved items (interpretation: "tracked" cards in the lineup are the saved ones, since I-bid-on-this items leave the lineup). Date-only closes count as end of day Chicago.
- Ended auto rows: the parser (`mbos_discovery.bid_events`) does not expose the e-mail Date header (its `observed_at` is the read clock), so the text is now `ended (read <date>)`; if a record carries `email_date`/`sent_at` it shows `ended (per your e-mail, <date>)`. F-153 wording changed accordingly (F-153's "per your e-mail" was really the read date). Need for lane 02: expose the Date header.
- No notifications, no bidding, no network, mail untouched.
- Tests: `tests/test_market_f154.py` (5; fixed clocks: 2 h boundary, CDT and CST today boundaries, sort, ended date source); f147/f152 pass. Reference 547 passed / 1 failed (known resale_f39 socket timeout); lane D+E 105 passed / 2 failed (known F-32).
- Browser check desktop+mobile: not done in this worker (no browser tool); Agent 01 browser check NEED.
