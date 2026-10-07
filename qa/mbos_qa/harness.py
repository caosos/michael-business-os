"""Harness factory — the plug-in seam between the acceptance suite and real lane implementations.

`MBOS_QA_IMPL` selects the implementation under test:
  * unset / "mock"         → this lane's reference mocks (every component reports IMPLEMENTATION=MOCK…)
  * "package.module:build" → a callable `build(workdir, *, mode, seed) -> Harness` supplied by lane A
    once real components exist. The acceptance tests do not change; only the harness does.
"""
from __future__ import annotations

import importlib
import os
import pathlib
from dataclasses import dataclass, field

from .contracts import Contracts
from .core import Clock, IdGen, iso
from .mocks import discovery, economics, governance, store, workflow
from .packet import ManualAssistEffector


@dataclass
class Harness:
    workdir: pathlib.Path
    contracts: Contracts
    clock: Clock
    ids: IdGen
    store: object
    kill: object
    pdp: object
    budget: object
    llm: object
    gateway: object
    effectors: dict
    artifacts: object
    workflow: object = None
    implementations: dict = field(default_factory=dict)

    def reopen(self) -> "Harness":
        """Simulate a process restart: new objects over the same durable files."""
        return build(self.workdir, mode=self.gateway.mode, seed=None, clock=self.clock, fresh=False)


def _mock_build(workdir, *, mode="mvp", seed=7, clock=None, fresh=True) -> Harness:
    workdir = pathlib.Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    clock = clock or Clock()
    ids = IdGen(clock, seed=seed)
    c = Contracts()
    st = store.ReferenceStore(workdir / "ledger.sqlite3", contracts=c, clock=clock, ids=ids)
    kill = governance.KillSwitch(workdir / "panic.json")
    kill.initialise()
    effs = {
        "comms": ManualAssistEffector(name="dry-run comms (MOCK of Agent 06 effector)", details_kind="comms",
                                      effect="send", log_path=workdir / "provider_comms.sqlite3",
                                      out_dir=workdir / "packets"),
        "publish": ManualAssistEffector(name="manual-assist publisher (Agent 07)", details_kind="marketing",
                                        effect="publish", log_path=workdir / "provider_publish.sqlite3",
                                        out_dir=workdir / "packets"),
    }
    gw_pid = st.kv_get("gateway_prov")
    if gw_pid is None:
        gw_pid = ids.new("prov")
        with st.tx() as t:
            t.put_provenance({"provenance_id": gw_pid, "created_at": iso(clock.now()), "actor_type": "system",
                              "basis": "FACT", "tool_name": "mbos_qa.mocks.governance.Gateway", "tool_version": "0.1.0"})
            t.cur.execute("INSERT INTO kv VALUES ('gateway_prov', ?)", (gw_pid,))
    gw = governance.Gateway(st, kill, governance.PDP(), governance.BudgetLedger(hard_cap_usd=0.0), effs, clock,
                            mode=mode, prov_id=gw_pid)
    h = Harness(workdir=workdir, contracts=c, clock=clock, ids=ids, store=st, kill=kill, pdp=gw.pdp, budget=gw.budget,
                llm=governance.LLMBudget({"agent-02-discovery": 0.50, "agent-03-economics": 0.50, "agent-07-marketing": 0.25}),
                gateway=gw, effectors=effs, artifacts=discovery.ArtifactStore(workdir / "artifacts"),
                implementations={
                    "A core workflow": workflow.IMPLEMENTATION, "B discovery": discovery.IMPLEMENTATION,
                    "C economics": economics.IMPLEMENTATION, "D state/receipts": store.IMPLEMENTATION,
                    "E governance": governance.IMPLEMENTATION,
                    "06 comms effector": "MOCK dry-run comms → manual-assist packet (Agent 07 effector)",
                    "G manual-assist packets": "REAL (this lane)",
                })
    h.workflow = workflow.Workflow(h)
    return h


def build(workdir, *, mode="mvp", seed=7, clock=None, fresh=True) -> Harness:
    impl = os.environ.get("MBOS_QA_IMPL", "mock")
    if impl == "mock":
        return _mock_build(workdir, mode=mode, seed=seed, clock=clock, fresh=fresh)
    mod, _, fn = impl.partition(":")
    return getattr(importlib.import_module(mod), fn)(workdir, mode=mode, seed=seed, clock=clock, fresh=fresh)
