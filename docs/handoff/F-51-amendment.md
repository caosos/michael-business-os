# F-51 amendment (owner Michael via Arya 0420 + 0433), recorded by Agent 01, coordinator-owned

Authoritative scope is the F-51 row in `docs/status/READY_QUEUE.md` (the AMENDMENT paragraph). Read it with
`git show origin/research/agent-01-coordinator:docs/status/READY_QUEUE.md`.

Order of delivery (do not reorder): (A) strict price/radius/unknown handling and visible validation; (B) Craigslist-style gallery with customizable category rows; (C) preference learning last, never delaying A or B.

Worker handoff state (honest): the F-51 worker was already running (started about 04:28Z) when this amendment was written (about 05:10Z). A running `claude -p` worker cannot be messaged. It reads this only if it re-fetches the queue. Proof it read it = its receipt or status citing "AMENDMENT". Until then the state is NOT READ. F-52 exists so that nothing in (A)(B)(C) is lost: it runs after F-51 and does only what F-51's receipt shows as not done. No second concurrent worker, no edits to the running worker's code or worktree, no restart.
