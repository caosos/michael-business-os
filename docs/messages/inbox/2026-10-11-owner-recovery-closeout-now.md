# OWNER DIRECTIVE — recovery closeout now

**Owner:** Michael Chambers  
**Time:** 2026-10-11 01:59 CDT  
**Priority:** P0 operations

Michael confirms the laptop SSH tunnels/ports are reachable and a replacement Agent 01 cloud session opened; the older duplicate was closed. Do not treat those observations as proof of the complete control chain.

Close the reboot recovery before taking unrelated work. Preserve the single existing `mbos-agent-01` coordinator and existing READY_QUEUE. Do not create duplicate coordinators or queues.

Required acceptance evidence:

1. `http://127.0.0.1:8479/health.json` answers from the current `michaelos` watchdog process.
2. Watchdog runs without `--no-wake`, with `MBOS_ALLOW_TMUX_WAKE=1`, and `var/watchdog/mode.json` has `"wake": true` under Michael's existing narrow authorization.
3. The current `mbos-agent-01` session is the only coordinator and is attached/resolved by the watchdog.
4. `mbos-dev-ui` and `mbos-dev-worker` are healthy; `:8766` answers.
5. Dispatcher state is correct: running when compatible READY work exists; cleanly idle/stopped when none exists; no duplicate workers.
6. `loginctl show-user michaelos -p Linger` reports `Linger=yes`.
7. Install/enable the narrow user-level persistence required for the watchdog and DealSniffer stack to recover after reboot. Do not invent a duplicate startup path; reconcile with existing `ops/systemd` and runbooks. Record exact installed unit names and `systemctl --user is-enabled/is-active` results.
8. ACK both this message and `2026-10-11-owner-reboot-recovery-five-minute-no-idle` on `research/agent-01-coordinator`, then post WORKING, followed by DONE or a structured NEED with one exact fix.
9. Run a bounded end-to-end test: delivery detected → existing idle Agent 01 awakened → ACK/WORKING receipt, without a duplicate session.
10. Record process IDs, command lines, loaded coordinator revision, health responses, queue state, and test timestamps in a durable receipt.

Existing authorization remains narrow: no bids, purchases, seller contact, spending, or unrelated external actions. Continue compatible approved work after the closeout receipt.
