# F-155 step 2: owner resale price input on DealSniffer Suggestions

- Provenance: Agent 01 review 2026-10-12T06:56:33Z (real GSA cache: 0 ranked, all "needs research", no way to enter `resale_targets`); builds on 8fc0112.
- Change: `POST /market/resale` (CSRF-checked, no PIN, nothing sent/spent) stores `resale_targets[lot]` in the local market prefs; empty value clears. "My resale price $" + Save on each Needs-research row, each ranked card and each outside-rules row. Owner-priced lot is ranked by the engine, resale labelled "your resale price (owner-set, not a sold comp)".
- Engine: `_bisect_int/_with/compute` have no public mbos_economics equivalent (checked); kept, with a comment naming the private dependency for lane 03.
- Tests: f155 9 passed; ref 555 passed / 2 failed (f145 golden = intended form markup, golden regenerated and green; known resale_f39); lane D+E 105 passed / 2 failed (known F-32).
- Not done: browser check (Agent 01).
