# Receipt: ARYA-20261010-1818-state-task-id-correction

- **Done (docs only):** renamed the state-filter row `F-61S` to `F-136` in `docs/status/READY_QUEUE.md`. Same row, not duplicated. Scope, lane 06, READY and the `F-61` dependency are unchanged. The old ID is mentioned once in the row text as the correction note. No other row was touched.
- **Why F-136:** `tools/foreman.py:parse_queue` only accepts `[A-GX]-\d+`, so `F-61S` was invisible. The highest F-nnn across docs/tools on all remote branches is F-135. F-150, F-250 and F-800 also appear, so F-136 collides with nothing.
- **Parse proof** (`foreman.parse_queue` on the edited file):
  - exactly 1 row with id `F-136`: status READY, agent 06, deps `F-61`
  - `deps_met` = True with F-61 in the done set and False without it (the F-61 queue row is still READY)
  - `ready_for(rows, '06', {'F-61'})` = `['F-136']`
- **Dispatcher state:** `tools/foreman.py --no-fetch` shows every lane CLOSED, with no claims and no active worker. Nothing was disturbed. Lane 06 head is 755869a. The survey reads the queue from `origin/research/agent-01-coordinator`, so it shows `ready=-` for 06 until this edit is published. Pre-existing warnings: schema warnings for B-13, A-21 and X-03, and "queue stale for 06".
- **Tests:** no code changed and no test suite was run. The checks above are the actual existing parser functions run on the edited file.
- **Remaining:** publish this commit. After publish, rerun `foreman.py` to confirm lane 06 lists F-136 as ready, then observe the actual START of F-136 separately. I did not add parser semantics, a worker, a live reload or any spend.
