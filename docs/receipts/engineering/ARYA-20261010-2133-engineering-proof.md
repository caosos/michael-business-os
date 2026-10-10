# Engineering receipt: ARYA-20261010-2133-engineering-proof

## START 2026-10-10T21:35:31+00:00
- Executed by the interactive engineering session: pid 2937731, entrypoint cli, kind interactive. This is not the pickup watcher.

## DONE 2026-10-10T21:35:31+00:00
- Result: nonce arya-2133-eng-proof-c8f2
- Next eligible approved task (deps met, Done history honoured): A-53 (ARYA-20261010-0633 remainder) `tools/foreman.py` parse_queue: surface malformed queue row

## Evidence summary (A-63 live proof)
- Nonce echoed: `arya-2133-eng-proof-c8f2`. Delivered by the session's own Monitor (task bdbh7vwvt, `tools/next_work.py --watch 120`) as "NEW INSTRUCTION ARYA-20261010-2133-engineering-proof" at about 21:34Z; no paste, no sync request to Michael.
- Automatic pickup ACK (distinct from execution): origin ack stage "ACKED ... AWAITING the interactive engineering session" at 2026-10-10T21:34:17Z (pickup adopted the new type automatically; it did not execute or complete it).
- Engineering execution: START/DONE above by interactive session pid 2937731 (entrypoint cli).
- Duplicate handling: a second `begin` after DONE returned DUPLICATE_IGNORED, a second `finish` returned already_done with the same next task; the receipt still has exactly one START and one DONE.
- Limits: session-owned 120 s polling; the Monitor expires after 30 minutes and must be re-armed by the session; no delivery after logout or durable restart is claimed.
