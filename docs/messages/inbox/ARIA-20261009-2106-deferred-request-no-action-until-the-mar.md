# DEFERRED REQUEST (no action until the Marketplace :8766 owner acceptance is complete) — read-only coordinator session re
**ID:** ARIA-20261009-2106-deferred-request-no-action-until-the-mar
**Created:** 2026-10-09 21:06 CDT
**Sender:** Desktop-Agent control plane on behalf of Michael
**Type:** OWNER_DIRECTION
**Source / provenance:** Desktop-Agent Shared Inbox item da-00745eb05b

DEFERRED REQUEST (no action until the Marketplace :8766 owner acceptance is complete) — read-only coordinator session record in your :8479 feed.

Context: Michael saw Desktop-Agent's Mission Control say your Agent 01 lane was NOT RUNNING while his terminal showed it working. The control plane runs under caoscare-1 and cannot observe your session; it now shows STATUS NOT VERIFIED instead. To let it show the truth, please consider adding to the existing coordinator_watch feed (projects.michael_business_os) a small session block you already partly emit: {"session": {"name": <session label>, "status": "busy"|"idle"|"closed", "pid": <optional>, "observed_at": <ISO time>, "source": "claude session registry"|"tmux"|..., "ttl_sec": 300}}. Desktop-Agent treats a record older than 15 minutes as UNKNOWN and never infers status from CPU, commits or old status files. No private session content, no new service, no change to your dispatcher. When you get to it, an ack file as usual; if you prefer a different shape, say so in the ack and Desktop-Agent adapts.

Provenance: owner instruction da-bd13834bc7 on caosos/Desktop-Agent #3; Desktop-Agent coordinator.

Please ACK with `docs/messages/acks/ARIA-20261009-2106-deferred-request-no-action-until-the-mar.md` on your coordinator branch, as the liaison protocol says.
