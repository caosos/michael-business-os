# B-45 — everyday local-deal import seam

Date: 2026-10-13

## Implemented

- Extended the existing authoritative `market_sources.REGISTRY`; no parallel source registry was created.
- Added `Authorized local deals` with evidence-gated states. No record is `LIVE CONNECTED`: a successful reviewed import is `IMPORTED`; no active imported offer is `NOT CONNECTED`.
- Added an account-scoped, append-only normalized import journal for five current everyday-deal classes: grocery/meat, restaurants, fuel/automotive, entertainment/tickets, and retail/local services.
- The seam accepts only a trusted reviewer-supplied public offer with an original public URL, or an authority-attested vendor submission with its submission ID. It records source, geography, retrieval path, observation/import/expiration timestamps, price/unit, availability, terms, and provenance.
- Expired offers are automatically excluded. Active imports use the same Marketplace location, category, price, source, search, pagination, Save/Hide, and detail-page path as other cards.
- The Sources panel and Settings onboarding show actual `IMPORTED` / `NOT CONNECTED` state, active count, last import, constraints, and next step. A reviewed import never upgrades itself to a live vendor feed.
- Deal cards preserve cents and units (for example `$1.99 per pound`). Their detail page shows deal facts and provenance rather than auction-only bid fields.

## Explicitly not implemented

- No vendor or public website was fetched or scraped.
- No offer was invented, imported, published, deployed, claimed live, redeemed, purchased, or sent.
- Review workflow permissions and a continuous vendor feed remain separate future work.

## Verification

- `PYTHONPATH=/tmp/ds-ui-lane02/src:/workspace/scratch/2d9530a13956/michael-business-os/src python3 -m pytest -q tests/test_local_deal_sources.py tests/test_source_onboarding.py`
- Result: **17 passed**.
- Changed modules also passed `python3 -m py_compile`; `git diff --check` passed.
- The larger assembled HTTP suite was not runnable in this isolated worktree because its DBOS runtime dependency is absent here. No deployment or browser claim is made.

## Next exact onboarding need

Obtain one current Conway-area offer from an authorized business contact (or its official public offer page) with: business/source name, stable offer ID, category, deal price and unit, regular price if stated, exact location, availability, observed timestamp, expiration timestamp, terms, and original URL or authority-attested vendor submission ID. Review it, import it through this seam, then capture loaded desktop/mobile evidence before calling the source visible or current.
