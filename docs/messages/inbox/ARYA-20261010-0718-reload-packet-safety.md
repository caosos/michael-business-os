# Review only: prepared reload packet safety, no live execution

tools/reload_ui.sh in the prepared packet appears to use set -u only. If cp -a of live to backup fails, execution can continue into stopping/removing the current UI. The export pipeline also lacks pipefail, and HTTP200 alone cannot prove the intended artifact is loaded.

Within the existing final recovery-packet work, make backup and export validation explicit prerequisites. Abort before stopping any live process or altering live files on any failed or incomplete backup/export. Validate expected paths/artifacts and retain a recoverable rollback. Add isolated failure-injection tests for backup/export failure proving no stop/remove operation runs, and test successful staged path. Prepare an exact artifact identity plus semantic route verification for post-reload, rather than HTTP200 alone.

Do NOT run this against live8766; owner approval is still pending. No new product feature, service installation, credentials or duplicate worker. Reuse the existing coordinator/recovery-packet route and report tested safety evidence with the packet.