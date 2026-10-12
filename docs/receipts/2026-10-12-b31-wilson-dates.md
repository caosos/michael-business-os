# B-31 receipt: Wilson Live/Simulcast date parsing with explicit UNKNOWN reasons

- **Task:** B-31 (P2, lane 02, B-28 follow-up). DRY-RUN; no request made (archived page only, `tests/fixtures/wilson/auctions.html`, provenance in the B-28 receipt).
- **Finding (FACT):** the card's single date line ("Oct 14 2026 – 11:00am CST") was already parsed by B-28 into `begins_at` (INFERENCE, America/Chicago local). All 11 Live/Simulcast events in the archive have a parsed start; none publishes an end time, so `closes_at` stays UNKNOWN.
- **Change:** `date_reasons()` in `adapters/wilson_site.py` plus a `date_unknown_reason` field: states why each UNKNOWN date is UNKNOWN (live card has one start only; 'Active'; no date line; unparseable text). Empty when both dates are parsed.
- **Tests:** 2 new in `tests/test_b28_wilson_site.py` (11/11 live events: parsed start + explicit end reason, 0 requests; unparseable/absent/Active cases). Full suite `pytest -q` = **383 passed, 0 failed**.
