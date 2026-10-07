# Agent 02 discovery fixtures (read-only copy)

`items.json` contains the Item v1 documents that **Agent 02's own pipeline** produced from Agent 02's own fixtures. The copy is for C-01 acceptance ("an Item from 02's fixtures gets valid economics...").

- **Source:** `origin/research/agent-02-opportunity` @ `7b4d9a8`, exported read-only with `git archive`. No merge was made, and Agent 02's worktree was not touched.
- **Command:** `mbos-discover --data-dir <tmp> run --config config/discovery.example.toml --fixtures tests/fixtures/ebay`, with `tests/fixtures/intake/{website_form,referral}` copied to `var/intake/`.
- **Output:** the run reported `items in store: 10` (ebay 6 new; website_lead 3 new; referral 1 new, 1 merged, 1 quarantined). Items are sorted by (type, category, title).
- **Content:** all values are fixture data (example.invalid contacts and synthetic listings). None of it is real.

Agent 02 owns the producer. Regenerate this file when 02's normalization changes.
