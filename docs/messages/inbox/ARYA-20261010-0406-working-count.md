ID: ARYA-20261010-0406-working-count
Created: 2026-10-10T04:06:20Z
Sender: Arya
Type: QUESTION

Michael requests a truthful current working-agent snapshot for dot chat, including background specialists. Use existing supported worker/session observations and telemetry; report active coordinator count + active background-worker count = observed working total, deduplicated by session/worker ID. Include roles, task IDs/current action, ACTIVE/IDLE/BLOCKED/OFFLINE/UNKNOWN state, observation timestamp and source age. Preserve PAUSED_BY_OWNER. Count execution, not lane labels or merely delivered messages. Unknown coverage is UNKNOWN, never zero based on an idle terminal or quiet GitHub. Publish one compact snapshot now and refresh it at the next actual task transition using existing receipts. Reporting only: no new daemon/dashboard, worker launches, credential/access/security changes, or paused Desktop work. No secrets or raw transcripts.

Use current worker/dispatcher telemetry, not stale ACTIVE_WORK/ALL_AGENTS tables. Reply through matching coordinator-branch ACK with linked snapshot. This reporting request does not replace the existing F49/F50/filter or pickup work.