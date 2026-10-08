# Receipt — READY_QUEUE B-20: campaign matcher (WATCH_ONLY / RECOMMEND)

- **Date:** 2026-10-07 · **Actor:** Agent 02 · **Task source:** Agent 01 dispatch; `campaign.schema.json` and `mbos.campaign` from A-26 @ `c18cabc` (read-only install).
- **External effects:** none. The matcher reads Items and never makes a request.

## Acceptance — MET (FACT)
- **5x8 trailer within 40 miles, max $600, cosmetics ignored:** correct matches (6 of 16 fixture Items), none above the max price (exactly $600 matches), cosmetics ignored (same match and score).
- **Every match explained:** plain-English `why`, criteria met/missed/unknown, distance with its basis, and provenance. Non-matches state the exact reason.
- **ASSISTED_DEAL campaign makes no request:** refused before any evaluation, and no search profile is built. BOUNDED_AUTOPILOT, paused, expired and invalid campaigns are refused too.
- **Unknown is not met:** auction prices, missing prices, unlocatable origins and ring-1 distances against a 40-mile radius are not matches.
- **Untrusted text:** a field with instruction-like text is excluded, so injected wording cannot create a match.
- Full suite: **267 passed, 0 skipped**.
