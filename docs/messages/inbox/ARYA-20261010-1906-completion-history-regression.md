# Urgent bounded completion-history reconciliation

F138 evidence passed at22bb3ab/codeeda3eee. However22bb3ab replaced the ENTIRE lane06 AGENT_STATUS Done line (F137,F136,F61,F60 and historical tasks) with only F138; status0e30a92 only fills that ID. Foreman excludes tasks based on lane Done plus queue state; coordinator queue still has several completed rows READY. This can re-enable already-completed work.

Immediately inspect actual dispatcher/worker state, preserve any active work and do not redispatch completed tasks. Reconcile coordinator READY_QUEUE completed F61@e54e27a,F136@48d27b9,F137@d537b27,F138@22bb3ab to DONE using published source/status/receipts. Preserve F60 DONE, A57 READY and all latest owner text/dependencies. Docs-only pickup may make its authorized coordinator queue reconciliation; do not edit another lane worktree beyond permissions.

Owning lane/coordinator should restore the historical Done entries from eda3eee plus F138, not overwrite unrelated newer status. If lane-status write is unavailable, the coordinator queue reconciliation is still necessary to prevent reexecution. Verify exact uniqueIDs and existing foreman eligibility after both lane Done and queue Done are considered; no completed task should remain eligible.

Record any already-launched duplicate and exact safe disposition under existing authority; no blind process kill, new coordinator or liveUI action. Add this concrete Done-history regression to the existing A57 protection scope, not a new feature. Report completion of the data reconciliation separately from A57 code, which still needs owning engineering session.

No live8766 reload, inventory fetch, billing expansion or implementation task.
