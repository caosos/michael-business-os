# Receipt B-41: untagged alerts to the owner, base_local from config

- Provenance: queue row B-41 (owner 2026-10-12: alerts mailbox dealsniffer2026@gmail.com; personal Gmail never used). Builds on B-40 (docs/receipts/2026-10-12-b40-peruser-alerts.md).
- Change: `peruser_alerts.ingest(..., untagged_user=None)`; when set, mail addressed to the plain `base_local@` from an authenticated alert sender goes to that user. Default None keeps quarantine. Unknown tags and DKIM-failing/spoofed mail are still quarantined. New `ingest_from_config` reads the `[peruser_alerts]` table (base_local, untagged_user, handles); example config sets `dealsniffer2026` and `owner`. The owner's local config was not touched.
- Evidence: tests/test_b41_untagged_owner.py (3 tests, fixtures only). Lane suite: 440 passed, 0 failed.
- DRY-RUN: no mailbox connection, no messages sent.
