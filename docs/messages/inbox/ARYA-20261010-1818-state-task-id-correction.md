# Correct the existing state-filter row ID; no new task

Read-only source review found the just-created F-61S row cannot be parsed. tools/foreman.py:parse_queue uses re.fullmatch(r"[A-GX]-\d+", c[1]); parse_status done extraction and dependency handling also expect numeric IDs. Therefore F-61S is silently invisible to the existing dispatcher.

Amend the SAME state-filter task from ARYA-20261010-1817 to a unique supported numeric F-nnn ID after checking all actual queue/task IDs. Preserve the complete scope, lane06, READY status and F61 dependency. Remove the invalid F-61S row rather than duplicating it. Do not expand parser semantics or add another feature. Do not alter unrelated historical QA references. Verify with the actual existing foreman parse/survey that precisely one state-filter task is visible and its dependency is resolved from F61 Done (lane06 e54e27a / status755869a now published).

Do not disturb active workers; first check actual dispatcher state. Publish corrected ID and parse/eligibility proof, then actual START separately when observed. Note the row already exists on the published coordinator branch a99a370, despite receipt wording about needing a future pickup merge; do not reintroduce stale queue merges.

Preserve A57 regression-protection scope and owner instructions. No live UI reload, new worker/coordinator, provider fetch or billing expansion.
