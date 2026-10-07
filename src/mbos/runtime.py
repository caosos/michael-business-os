"""Runtime wiring: settings + DBOS + the app-database datasource + lane components.

One process = one runtime. `init_runtime()` must run before `DBOS.launch()` (DBOS requires
datasources to exist before launch); `launch()` then recovers any PENDING workflows, which is
how a crash mid-ACT resumes (A5) and a HOLD survives a restart (A6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypeVar

import sqlalchemy as sa
from dbos import DBOS, DBOSClient, DBOSConfig, SQLAlchemyDatasource

from mbos.config import Settings, configure, settings
from mbos.db.engine import app_engine, sqlalchemy_url
from mbos.db.migrate import migrate
from mbos.interfaces import (
    ActionPlanner, Deduper, Researcher, Gateway, KillSwitch, LLMBudget, Normalizer, Notifier, PolicyDecisionPoint, Scorer,
    SourceAdapter,
)

R = TypeVar("R")


@dataclass
class Components:
    """Lane implementations. Defaults are the reference stubs; owning lanes swap in theirs."""

    adapters: dict[str, SourceAdapter] = field(default_factory=dict)
    normalizer: Optional[Normalizer] = None
    deduper: Optional[Deduper] = None
    planner: Optional[ActionPlanner] = None
    scorer: Optional[Scorer] = None
    researcher: Optional[Researcher] = None  # when set, RESEARCH runs before SCORE (A-05)
    pdp: Optional[PolicyDecisionPoint] = None
    kill_switch: Optional[KillSwitch] = None
    gateway: Optional[Gateway] = None
    notifier: Optional[Notifier] = None
    llm_budget: Optional[LLMBudget] = None

    def with_defaults(self, state_backend: str = "reference") -> "Components":
        from mbos.reference.action_planner import DefaultActionPlanner
        from mbos.reference.fixture_adapter import ExactKeyDeduper, FixtureNormalizer
        from mbos.reference.governance import (
            DenyByDefaultPDP, DryRunEffector, LedgerLLMBudget, ReferenceGateway, TableKillSwitch,
        )
        from mbos.reference.notify import OutboxNotifier
        from mbos.reference.placeholder_scorer import PlaceholderScorer

        if state_backend == "lane_d":
            from mbos.reference.governance_lane_d import LaneDDryRunEffector, LaneDReferenceGateway, PanicKillSwitch

            self.kill_switch = self.kill_switch or PanicKillSwitch()
            self.gateway = self.gateway or LaneDReferenceGateway(LaneDDryRunEffector(), self.kill_switch)
            self.notifier = self.notifier or NullNotifier()  # lane D's receipt trigger writes the outbox
        self.normalizer = self.normalizer or FixtureNormalizer()
        self.deduper = self.deduper or ExactKeyDeduper()
        self.planner = self.planner or DefaultActionPlanner()
        self.scorer = self.scorer or PlaceholderScorer()
        self.pdp = self.pdp or DenyByDefaultPDP()
        self.kill_switch = self.kill_switch or TableKillSwitch()
        self.gateway = self.gateway or ReferenceGateway(DryRunEffector(), self.kill_switch)
        self.notifier = self.notifier or OutboxNotifier()
        self.llm_budget = self.llm_budget or LedgerLLMBudget()
        return self


class NullNotifier:
    def notify(self, conn, *, kind, item_id, action_request_id, summary) -> None:  # noqa: ANN001
        return None


@dataclass
class Runtime:
    settings: Settings
    components: Components
    datasource: SQLAlchemyDatasource
    engine: sa.Engine


_RT: Optional[Runtime] = None


def runtime() -> Runtime:
    if _RT is None:
        raise RuntimeError("mbos runtime not initialised; call mbos.runtime.init_runtime()")
    return _RT


def spine_module():
    """The spine backend for this runtime: `mbos.spine` (reference DDL) or `mbos.spine_d` (lane D)."""
    if _RT is not None and _RT.settings.state_backend == "lane_d":
        from mbos import spine_d

        return spine_d
    from mbos import spine

    return spine


def components() -> Components:
    return runtime().components


def init_runtime(s: Settings, comps: Optional[Components] = None, *, launch: bool = True) -> Runtime:
    """Configure, migrate, create DBOS + datasource, and (by default) launch — which recovers workflows."""
    global _RT
    import mbos.workflows  # noqa: F401 — registers workflows before launch

    configure(s)
    if s.state_backend == "reference":
        migrate(app_engine())  # lane D databases are migrated by lane D's own migrator
    config: DBOSConfig = {
        "name": s.app_name,
        "system_database_url": sqlalchemy_url(s.system_database_url),
        "application_version": s.application_version,
        "executor_id": "local",
        "log_level": "WARNING",
    }
    DBOS(config=config)
    ds = SQLAlchemyDatasource.create(sqlalchemy_url(s.database_url))
    _RT = Runtime(settings=s, components=(comps or Components()).with_defaults(s.state_backend), datasource=ds,
                  engine=app_engine())
    if launch:
        DBOS.launch()
    return _RT


def shutdown() -> None:
    global _RT
    DBOS.destroy(destroy_registry=False)
    if _RT is not None:
        _RT.datasource.engine.dispose()
    _RT = None


def tx(fn: Callable[..., R], *args: Any) -> R:
    """Run `fn(conn, *args)` in one READ COMMITTED transaction on the app DB.

    Inside a DBOS workflow the call is a checkpointed transaction step: its result is recorded in
    the same transaction, so on recovery it is never re-applied (exactly-once). Outside a workflow
    it is a plain transaction.
    """
    ds = runtime().datasource

    def body(*a: Any) -> R:
        return fn(ds.sql_session().connection(), *a)

    return ds.run_tx_step({"name": f"tx:{fn.__module__}.{fn.__qualname__}", "isolation_level": "READ COMMITTED"},
                          body, *args)


def client() -> DBOSClient:
    return DBOSClient(system_database_url=sqlalchemy_url(settings().system_database_url))


def item_workflow_id(item_id: str) -> str:
    return f"item:{item_id}"
