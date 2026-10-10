# A54 packet review: two remaining failure paths

09de842 addresses the original backup/export-before-stop defect. Reuse that work. Before describing the prepared recovery packet as verified, cover two narrow paths: rollback must not accept HTTP500 (or any response except000) as successful recovery; require the intended healthy semantic response. Also, failure of the post-stop rm step under set -e must invoke recovery or stop in an explicitly recoverable state, not exit with the UI down and no rollback attempt. Add isolated failure-injection tests for these paths, with no live8766 operation.

Describe artifact identity precisely: on-disk tree verification plus semantic route markers is not a SHA returned by the running process. Either provide a proven process/artifact binding using existing mechanisms or retain that specific limitation; do not expand into a new telemetry feature.

This is the existing coordinator-owned A54 packet correction, no new lane/duplicate worker. F59 continues independently; preserve it. No live approval has been received.