# Receipt: F-16, Edit and Retract on /notes

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-16` (claimed in `81ddded`)
- **Effect:** this branch only. Writes go only through `spine_d.record_operator_note` (edit) and `spine_d.retract_operator_note` (retract): append-only, receipted, human provenance.

## What was built
- `/notes` lists the current head of every note chain, retracted ones marked. Each live note has an inline **Edit** (pre-filled form; saves a **new version** with `supersedes` = the head) and **Retract** (a reason is required).
- Both need CSRF and the step-up PIN (unset = refused). The **author is server-set**; a posted `author` / `entered_by` is ignored. Every refusal is shown with all its reasons (elementary advice, FACT, missing model, bad kind or link, missing retraction reason, stale or retracted target).
- Only the head can be changed: an old version or a retracted note is refused with a reason.
- A static test pins R14: `retract_operator_note` is not referenced by workflows or runtime; only `backend.py` and `server.py` in the UI call it.

## Verification (FACT)
- Lane D/E suite: 11 note tests pass (full lane D suite in the final run).
- Edit: the DB row has `supersedes` = the old id, the old row still exists, and the live document holds only the new version. Retract: the note leaves the live document and **the next card of that model no longer shows the risk** (real lane-C engine + enricher), while `include_retracted` still shows it as RETRACTED.
- Mutation check: removing the PIN check fails the refusal test; file restored.
