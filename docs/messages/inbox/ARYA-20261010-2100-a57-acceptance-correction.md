# A57 bounded acceptance correction, same owning engineering work

Reviewed A57 commit85f34915,7guard+17pickup tests and concrete9435d68 replay. Preserve current engineering work/A50 if already started. No new feature or worker. Complete these original guard/history requirements before declaring A57 accepted:

1. tools/pickup_git.py:queue_problems returns [] when either up or mine is empty. Deleting the entire READY_QUEUE or a failed git-show therefore bypasses the fail-closed guard. Distinguish absent initial baseline from failed read and deletion of an established queue; refuse unsafe/unreadable candidate and retain upstream. Focused regression: existing queue -> whole file removed/empty and read failure must not publish.
2. tools/queue_guard.py only checks deps/agent becoming EMPTY. Dropping one of several dependencies or replacing owner with another nonempty value silently passes. Preserve dependency/task-owner semantics against parents unless explicitly attributable authorized edit, with focused partial-dependency removal/owner replacement cases. Do not require blind textual equality for harmless formatting.
3. ARYA-1906 requested full lane06 Done history restoration from eda3eee plus F138, preserving newer entries; latest1fa2a720 still only three header entries. Central DONE correction812072f9 prevented further eligibility, but lane history remains incomplete. Restore through owning authorized route, no old wholesaleoverwrite, and protect status writers from replacing a full completion history with only latesttask (concrete22bb3ab regression). No completed task redispatch.
4. Existing marker plumbing is not connected to publish and is correctly disclosed. Keep unauthorized reopen/cancel blocked; no automatic authorization from marker text alone.

Reconcile current queue/status/receipts first. Existing Agent01 engineering handles this correction through its current session; pickup docs-only must give precise handoff status rather than fabricate execution or launch another coordinator. Report code/test/actualruntimeadoption separately and preserve central F60/F61/F136/F137/F138 DONE. A50 is existing next task, not a new task from this message; no claim it is complete without source/test evidence.

Live A58 is successful and must not be rerun. No liveUI changes, cachefetch, extra billing, security expansion or otherproject work.
