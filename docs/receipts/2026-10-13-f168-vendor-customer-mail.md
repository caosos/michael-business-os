# F-168 — Verified vendor/customer mailbox intake

Date: 2026-10-13 13:26 America/Chicago  
Worktree branch: `research/agent-06-vendor-mail`  
Published branch: `research/agent-06-communications`  
Base: `99de5a16` (`origin/research/agent-06-communications`)  
Stage: IMPLEMENTED / NOT DEPLOYED / MAILBOX NOT CONNECTED

## Bounded result

- Added one private verified-vendor registry. A sender address can map to only
  one verified DealSniffer customer account, and onboarding records the vendor,
  business/location, verification timestamp and proof reference, authority,
  contact permission, and freshness commitment.
- Added a provider-neutral importer over the existing read-only mailbox-reader
  interface. The included operator command reuses lane 02's `ImapReader`
  (`readonly=True` plus `BODY.PEEK[]`) and requires both explicit `--live` and
  separately configured environment secrets before any connection.
- Approved, DKIM-authenticated vendor messages in the explicit
  `DEALSNIFFER DEAL` format become `REVIEW_PENDING` records in the existing
  `vendor_deals.Store`. They never publish directly.
- Preserved title/product, exact deal and regular prices, unit, location,
  availability, observed/start/expiration, terms, original URL, optional photo,
  provider receipt and message provenance.
- Unknown, unverified, unauthenticated, malformed, or missing-message-ID mail is
  appended to a private quarantine journal with `published: false`; raw message
  bodies are not stored there.
- Deduplication is atomic in the existing vendor-deal journal and refuses both a
  repeated Message-ID and an identical vendor-offer identity under a new ID.
- Added a review mapping into the existing `local_deal_sources.normalize` path.
  Review remains an explicit separate action; the normalized Marketplace card
  now retains an available vendor photo.

## Evidence

Command:

```text
PYTHONPATH=/tmp/ds-plan/src:/tmp/ds-ui-lane02/src:$PYTHONPATH \
  python -m pytest -q tests/test_vendor_mail.py tests/test_local_deal_sources.py
```

Result: `18 passed in 0.44s`.

Additional syntax verification:

```text
python -m py_compile operator_ui/vendor_mail.py operator_ui/vendor_deals.py \
  operator_ui/local_deal_sources.py tools/import_vendor_deal_mail.py
```

Result: PASS.

The new tests prove:

1. one verified sender maps to one customer account;
2. authenticated mail creates exactly one unpublished review-pending record;
3. precise offer facts, URL, photo, and receipt provenance survive parsing;
4. unknown and unauthenticated senders create no offer;
5. malformed mail creates no offer;
6. Message-ID and offer-identity replays are idempotent; and
7. the existing reviewed local-deal normalizer produces the future Marketplace
   card and retains the photo.

## Honest boundary / next proof

No real mailbox was read, no credentials were added, no mail was sent, and no
EliteDesk deployment occurred in this task. The next bounded proof is to onboard
one real authorized customer, configure the dedicated vendor inbox on the host,
ingest one genuine labeled test offer, review it, and verify its resulting card
in the actually loaded desktop and mobile Marketplace.
