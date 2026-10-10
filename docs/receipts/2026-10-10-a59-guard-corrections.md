# A-59: queue/history guard corrections (Agent 01): items 1, 2, 4 DONE; item 3 restore NOT applied (blocked)

**Code (committed):**
1. `pickup_git.queue_problems`: absent upstream baseline is allowed; a failed `ls-tree`/`show`, a missing or empty result against an established queue are refused (retaining upstream).
2. `queue_guard.check`: also flags one of several dependencies dropped and an owner replaced by an unrelated one (token overlap: `01` -> `01 engineering` is fine; `A-54, A-55` vs `A-54,A-55` is fine); an attributable `edit` marker still allows it.
4. Marker plumbing remains unconnected (publish passes none); marker text never authorises anything.
3a. `queue_guard.done_line_problems` + `worker.status_history_problems`: after every lane run the lane's `Done:` IDs before/after are compared and a loss is reported (stderr + `status_history_problems` in the worker result); the worker prompt now says to ADD to the Done line, never replace it. It warns, it cannot undo an already pushed commit.

**Tests:** test_queue_guard 11 pass (9435d68 replay still green; partial dep drop; owner replacement; Done-history replay of the real 22bb3ab vs eda3eee); test_inbox_pickup 19 pass (emptied queue, deleted queue, unreadable origin refused; absent baseline allowed); test_worker/foreman/dispatcher unaffected (61 passed together).

**Item 3, restore of lane 06's Done history: NOT done.** Writing to lane 06's branch was denied by the auto-mode classifier (modifies another lane's shared branch). The merged line (eda3eee entries + F-138, newer entries kept, check: no Done ID lost versus eda3eee or the tip) is prepared in `docs/handoff/lane06-done-line-restore.txt`. Needed: lane 06's own worker or the owner applies it (one docs line). Until then the coordinator queue DONE rows protect against re-dispatch. A-59 stays PARTIAL.

**Runtime adoption:** the running pickup watcher re-execs on change to `queue_guard.py`/`pickup_git.py`; the dispatcher/worker pick up `worker.py` on their next launch. Not separately restarted by me.
