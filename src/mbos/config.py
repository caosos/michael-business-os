"""Runtime settings. DRY-RUN is not a setting: the MVP has no live effector, and the
gateway refuses to run if anything claims otherwise (ADR-0005 guard check 8)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

DRY_RUN = True  # Round two / MVP: hard-coded. Changing this needs an ADR and MICHAEL_DECISIONS #4/#5.


@dataclass(frozen=True)
class Settings:
    database_url: str
    system_database_url: str
    app_name: str = "mbos"
    application_version: str = "mbos-spine-0.1.0"
    # Provisional defaults (MICHAEL_DECISIONS #1/#2 not yet decided); placeholder scorer only.
    approval_ttl_hours: float = 72.0
    approval_poll_seconds: float = 30.0
    llm_daily_cap_usd: dict[str, float] = field(default_factory=lambda: {"*": 0.0})
    dry_run: bool = DRY_RUN
    # "reference": Agent 01's own DDL (src/mbos/db/migrations). "lane_d": Agent 04's canonical store (R1),
    # migrated by lane D's own migrator; the spine then writes only through lane D's SQL API (mbos.spine_d).
    state_backend: str = "reference"
    # "reference": the spine's stand-in gateway; the spine writes action-status receipts itself.
    # "lane_e": Agent 05's ActionGateway (A-03, R4). The gateway owns every action-status edge and its receipts;
    # the spine moves only the Item. Requires state_backend="lane_d".
    gateway_mode: str = "reference"
    reconcile_crontab: str = "*/5 * * * *"  # E-05: settle stuck execution claims (never re-sends)


_override: Settings | None = None


def configure(s: Settings) -> None:
    """Set settings explicitly (tests, CLI). Clears cached engines bound to old URLs."""
    global _override
    _override = s
    settings.cache_clear()


@lru_cache(maxsize=1)
def settings() -> Settings:
    if _override is not None:
        return _override
    db = os.environ.get("MBOS_DATABASE_URL")
    sysdb = os.environ.get("MBOS_SYSTEM_DATABASE_URL")
    if not db or not sysdb:
        raise RuntimeError("MBOS_DATABASE_URL and MBOS_SYSTEM_DATABASE_URL must be set (see RUNBOOK.md: `mbos devdb up`)")
    return Settings(database_url=db, system_database_url=sysdb)
