# Owner-local decision cases (A-61; ARYA-2116/2117/2118)

**Status: capability implemented and tested with SYNTHETIC data. No real case has been imported, so nothing is "learned" yet.**

## Where a case lives
`var/private/decision_cases/cases.jsonl` on the owner's machine: git-ignored (`var/`), directory 0700, file 0600, append-only, hash-chained (MBOS-CJSON-1). The module refuses to write if the directory, or an import file, sits inside a git checkout and is tracked or not ignored. Override the location with `MBOS_DECISION_CASES_DIR` (same checks). No database, no network, no GitHub, no PIN, no credential.

## Secure import route (for Michael, on this machine; nothing goes through GitHub or chat relays)
1. `cd ~/business-os-worktrees/agent-01-coordinator && PYTHONPATH=src .venv/bin/python -m mbos.decision_cases template > ~/trailer-case.json` (the template has no values; keep the file OUTSIDE the repo, e.g. in your home folder).
2. Fill it in: stable `listing_id` (the GSA lot id) and `source`, `decided_at`, `decision` (pass/watch/pursue), `reason_summary` (a summary of the reasoning, not a transcript), `evidence` entries each marked `verified`, `owner_estimate` or `unverified` (condition, photos, dimensions/capacity, paperwork, costs, sold comparables, repair work), `owner_estimates` (always labelled as estimates), `alternatives_considered`, `uncertainty`, `missing_evidence`, `owner_skills`, `category_tags` (words used to find similar candidates). Dollar amounts are allowed here and stay on this machine.
3. `PYTHONPATH=src .venv/bin/python -m mbos.decision_cases import ~/trailer-case.json`. It validates everything first, writes nothing on any error, and prints only the listing id, row number and hash.
4. Read it back: `... show <listing_id> --source <source>` (effective case + history), `... verify` (chain), `... diagnose` (per-row integrity).
5. Later: `... outcome <listing_id> "what actually happened"` (owner-reported, kept apart from estimates). Delete `~/trailer-case.json` when done.

Michael can also have Agent 01 run steps 3 and 4 against the file once it is on this machine; the case text never needs to appear in GitHub or a message.

## Identity, integrity and estimates (A-64 corrections)
- A case is identified by **source + listing_id**. Importing the same pair twice, or twice inside one file, is refused before anything is written. `show`, `correct`, `outcome` and `reset` take `--source S`; a bare listing id works only if exactly one source has it, otherwise it is refused as ambiguous. Corrections can never change a case's source.
- **Integrity:** every read and write verifies the whole hash chain first. If any row was altered or is malformed, `show`, `propose`, `correct`, `reset` and `import` return an explicit INTEGRITY FAILURE (exit 3) and apply nothing; no proposal is generated. `diagnose` prints per row ok/problem with ids and hashes only (no case text); the file itself is never rewritten or discarded, so the owner can inspect it. Restoring the exact original bytes makes it valid again.
- **Estimates:** an evidence entry marked `owner_estimate` is shown in a proposal under `owner_estimates_not_facts`, labelled as an owner ESTIMATE (never under verified facts), with no need to repeat it in `owner_estimates`.

## Owner control
`correct <listing_id> PATCH.json --why "..."` appends a correction (history kept, original row untouched). `reset <listing_id> --why` stops learned use of that case (rows stay for audit). `disable` / `enable --why` switch all learned use off/on. Every change is a row with who, when and why.

## How it is applied (proposal-first)
`propose CANDIDATE.json` (a candidate: `listing_id`, `title`, optional `text`, `category_tags`, `evidence`) returns `PROPOSAL_FOR_OWNER_REVIEW`: for each similar active case (shared words in title/tags) the source case (listing id, row, corrections), the precedent decision and reason **for that one listing only**, verified facts apart from unverified evidence, owner estimates labelled as estimates (not facts, not applicable to the candidate), the uncertainty and missing evidence then, and which evidence kinds the case relied on that the candidate lacks. It never emits a bid amount, never changes a filter or gate, never treats a single pass as a category dislike, and does not match a listing against itself.

## Not done / limits
- Not wired into the live Marketplace UI or ranking (no live change was authorised); retrieval is a command. UI exposure is a separate row after review.
- Similarity is simple word overlap, deliberately explainable; it is a precedent finder, not trained ranking.
- The case store is not the Postgres spine: spine `Outcome` needs a spine Item and a fixed kind, `record_attestation`/`record_human_input` are narrow (300-char note, fixed keys), operator notes are make+model knowledge, cached /market lots are not spine Items, the resale Book is in memory. Using any of them would misfile the case as an acquisition or a false verification.
