# Pickup receipt: ARYA-20261010-2106-photo-access-evidence

Executed by automatic pickup (Agent 01), 2026-10-10. Dry-run, docs only.

## Verdict: GSA image access is UNKNOWN (not verified either way)
- The one representative unauthenticated fetch of
  `https://www.ppms.gov/gw/auction/ppms/api/v1/auction/image/31QSCI27006005.jpg`
  was **not performed**: the executor's sandbox denied the network command (curl). I did not retry, work around it or substitute another route.
- So there is no observed status, content type or redirect destination from this run.

## Existing evidence (reviewed, not re-observed)
- `docs/receipts/2026-10-10-marketplace-8766-reload.md` line 9 and READY_QUEUE F-48 item (4) state "GSA photos return HTTP 401 'Token expired or invalid' without a GSA login". Those texts do not record the exact URL, date/time of the request or the command, so by this instruction's standard they are a **recorded claim, provenance incomplete**, not a reproduced observation. It is a single-sample statement and must not be generalised to "all GSA images need a login".
- Code (source review on `origin/research/agent-06-communications`): `operator_ui/market_view.py::_photo` sends every URL for which `landing_fix.is_gsa_image(url)` is true to `landing_fix.photo_tile`, which never emits an `<img>`; `landing_fix.NO_PHOTO` ("Photo is behind GSA's login: open the original listing") is shown unconditionally. This confirms the dispatcher's finding: the rendering branch is fixed regardless of the real response, and a GSA login alone cannot change it.
- Verified original-listing fallback (`gsaauctions.gov/auctions/preview/<id>`, e.g. 378501) is retained; not touched.

## Smallest supported next step (for the serial plan; no UI work started)
1. **Owner/Arya decision needed:** authorise ONE ordinary unauthenticated GET/HEAD of the single URL above from the EliteDesk (or run it from a normal browser/terminal and paste status, content-type, redirect). No session, token, proxy or login.
2. If **200 image/***: the defect is the unconditional tile. Queue a code row for lane 06 (after A-60, serial): render `<img referrerpolicy=no-referrer loading=lazy>` for GSA image URLs with `onerror` fall back to the existing tile + original-listing link; change NO_PHOTO wording to "Photo unavailable" (not "behind login") unless a 401/403 was observed. Tests: image path, error fallback, no wording claim without evidence.
3. If **401/403**: record the denial, keep the tile, but reword the tile to cite the observed status/date; no bypass.
4. If still unreachable: keep tile, reword to "Photo not available here: open the original listing" (no universal-login claim).

No READY_QUEUE row was added: the next step is gated on the owner decision in item 1, and A-60 already notes "report the actual supported access dependency".

## Tests / numbers
None run (docs-only; no code touched). Network fetches performed: 0 (1 attempted, denied by sandbox).

## Remaining blockers
- Owner decision to allow the single read-only fetch (item 1).
- No bids, spend, contact, credentials, deploy, restart or other-project action taken.
