# B-32 receipt: Wilson Live/Simulcast date parsing (already delivered by B-31)

- **Task:** B-32 (P2, lane 02, B-28 follow-up). DRY-RUN; no request made (archived `tests/fixtures/wilson/auctions.html`; provenance in the B-28 receipt).
- **Finding (FACT):** the B-31 commit 4f69b33 already meets this acceptance: all 11 Live/Simulcast events parse `begins_at` as INFERENCE (America/Chicago); `closes_at` is UNKNOWN with an explicit `date_unknown_reason` (no end time published); absent/unparseable/'Active' dates are UNKNOWN with a reason (`tests/test_b28_wilson_site.py::test_b31_*`, `ad.summary["requests"] == 0`).
- **Change:** none to code (no duplicate logic added). This receipt records the verification.
- **Health:** `pytest -q` = **383 passed, 0 failed**.
