"""PANIC / kill switch (ADR-0005 §5, merged design).

  L1 agent       — freeze one agent_id: it can neither propose nor execute.
  L2 capability  — freeze a capability ("money.payment.send"), a prefix ("money.*"),
                   or a whole category ("category:sms").
  L3 global      — system_state=FROZEN: the gateway refuses every execution and every
                   new proposal; queued (approved, not started) requests are cancelled.

State lives in Postgres (ruling R5): lane D's sealed, append-only `mbos.panic_state`, written only
by `mbos.panic_set` together with its KILL_SWITCH_CHANGED receipt, read by `store_pg.PgPanicStore`.
(The wave-one JSON-file store was removed in E-02: one source of truth, backed up, receipted.)

FAIL CLOSED: a missing, unreadable, empty, wrongly-shaped or checksum-mismatched state — or no
database at all — is reported as FROZEN (L3). There is no code path that turns a read failure
into RUNNING.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA = "mbos.governance.panic/1"
RUNNING, FROZEN = "RUNNING", "FROZEN"


@dataclass(frozen=True)
class PanicState:
    global_state: str
    frozen_agents: dict = field(default_factory=dict)
    frozen_capabilities: dict = field(default_factory=dict)
    revision: int = 0
    readable: bool = True
    error: str | None = None

    @property
    def globally_frozen(self) -> bool:
        return self.global_state != RUNNING or not self.readable

    def blocks(self, agent_id: str | None, capability: str | None, category: str | None) -> list[str]:
        """Return the reasons this (agent, capability, category) is blocked; empty = clear."""
        if not self.readable:
            return [f"PANIC_STATE_UNREADABLE:{self.error}"]
        reasons = []
        if self.global_state != RUNNING:
            reasons.append("PANIC_L3_FROZEN")
        if agent_id and agent_id in self.frozen_agents:
            reasons.append(f"PANIC_L1_AGENT:{agent_id}")
        for key in self.frozen_capabilities:
            if category and key == f"category:{category}":
                reasons.append(f"PANIC_L2_CATEGORY:{category}")
            elif capability and (key == capability or (key.endswith(".*") and capability.startswith(key[:-1]))):
                reasons.append(f"PANIC_L2_CAPABILITY:{key}")
        return reasons
