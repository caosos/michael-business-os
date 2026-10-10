# Verify runtime adoption of existing dispatch repair

0633 recovery makes F56 dispatchable in source, but the published receipt establishes eligibility only, not actual launch. No new feature row is requested.

Inspect the existing running dispatcher PID, start time and actual loaded code revision, latest F56 launch or skip reason, worker ownership/lock, attempt counter, quota and dirty-worktree guards. Publish timestamped observed facts. If the persistent dispatcher still runs pre-c7d8524 code, apply the existing routine safe dispatcher reload/recovery path only after checking active workers and preserving them; this is not authorization to reload the Marketplace UI, install a service, expand permissions or bypass quota guards. If F56 already runs, leave it alone and publish its execution evidence. If blocked, diagnose and correct a recoverable in-scope delivery condition without duplicate workers or repeatedly burning attempts. Keep F57 gated behind actual F56 completion.

Latest owner asks productive progress overnight within included allowance. No extra paid usage or unrelated changes. Report actual execution separately from ACK and queue readiness.
