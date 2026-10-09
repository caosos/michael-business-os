# Owner approval packet (one reply answers everything)

Prepared by Agent 01, 2026-10-09. Everything not listed here proceeds without you through the dispatcher, DRY-RUN only. Default if you say nothing: the "Recommended" answer is NOT assumed; each item stays as it is today.

## Requested permissions in total
1. You run three commands in your own terminal to install the Agent 01 self-wake (Q1). I cannot, and will not try to, install it myself.
2. Read-only fetches of public auction pages that their terms allow (Q3). No login, no bids.
3. Two host actions you run yourself (Q8, Q9). Nothing else.

Never granted by this packet: any purchase, bid, spend, seller contact, listing, payment, deployment, or change to Claude permissions.

## Decisions
| ID | Question | Recommended | Unblocks | Rollback |
|---|---|---|---|---|
| Q1 | Install the narrow self-wake yourself (commands below) | YES | Agent 01 wakes for approved READY work and owner messages, idle-only, 6 per hour max | set `var/watchdog/mode.json` to `{"wake": false}` |
| Q2 | Money per purchase. Today: $500 per deal and $500 total. Your example: tying up $1,000 to earn $400 | A: keep $500 until the first receipted sale, then raise to $1,000 per deal only when sold comps back it and days to cash is 7 or less | cards can show deals above $500 as "needs your capital decision" instead of PASS | edit `config/operator_profile.v1.json` |
| Q3 | Allow read-only fetches of public auction pages (rate limited, every fetch receipted) | YES | B-23 live Arkansas auction data instead of fixtures | turn the source off in config |
| Q4 | Treat labor and service leads as out of the main workflow (code and history kept) | YES | cards, mission and Today show asset deals only | none needed; it is a filter |
| Q5 | When your resale price differs from the system's, rank by yours and show both | YES | the splitter case: your $1,500 vs the system's $900 | none needed |
| Q6 | Show no-title or bill-of-sale trailers as their own class with title path, cost and delay; never assume transfer | YES | paperwork-discount deals | none needed |
| Q7 | Automated bidding and delegated buying rules | DEFER | later; the system only watches and suggests max bids now | n/a |
| Q8 | Host: stop and disable `mbos-foreman.service` (sudo, you run it) | YES | removes the old idle watcher | `sudo systemctl enable --now mbos-foreman` |
| Q9 | Host: `sudo loginctl enable-linger michaelos` | YES | database and services survive a reboot | `sudo loginctl disable-linger michaelos` |
| Q10 | Off-box backup destination (decision #11) | B encrypted cloud storage, else A another machine | restore drills | n/a |
| Q11 | eBay developer keys (decision #8, B-12) | DEFER | eBay data; auctions come first | n/a |
| Q12 | Numbers: cash goal $2,000 in two weeks is recorded as a goal only. Hours per week you can work, and your current cash situation | write them in the reply | the mission planner stops saying UNKNOWN | edit the profile |

## Q1 commands (you run these; they are exactly what I would have run)
```
cd ~/business-os-worktrees/agent-01-coordinator
git add tools/coordinator_watch.py tests/unit/test_coordinator_watch.py && git commit -m "agent 01: narrow self-wake (owner-installed)" && git push origin research/agent-01-coordinator
echo '{"wake": true, "reason": "owner-installed 2026-10-09"}' > var/watchdog/mode.json
tmux kill-session -t mbos-watchdog; tmux new-session -d -s mbos-watchdog 'cd ~/business-os-worktrees/agent-01-coordinator && MBOS_ALLOW_TMUX_WAKE=1 exec .venv/bin/python -u -I tools/coordinator_watch.py --serve-port 8479 --interval 120 2>&1 | tee -a var/watchdog/daemon.out'
```
What it can do: type one fixed line (ids only, "no purchases, sales, seller contact, spending or deployment") into the `mbos-agent-01` pane only, only when that session is idle, at most once per 10 minutes, 3 per item, 6 per hour, never under the quota guard. The 16 local tests pass; the live end-to-end test has not been run, so nothing about it is verified yet.

## Copy and edit this reply
```
Q1 YES   Q2 A   Q3 YES   Q4 YES   Q5 YES   Q6 YES   Q7 DEFER
Q8 YES   Q9 YES  Q10 B    Q11 DEFER
Q12 hours per week: __   cash situation: __
```

## What starts automatically after you answer
Q3 YES: B-23 switches from fixtures to the permitted live pages. Q2 and Q5: C-33 uses them in the next scoring run. Q1: Agent 01 starts waking on READY work. The rest only change filters or host settings.
