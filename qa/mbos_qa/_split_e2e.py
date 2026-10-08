"""G-18 child process: the REAL runtime with SPLIT logins (workflow = mbos_dbos, owner = mbos_operator_ui; D-26). Prints one JSON line.
Run with MBOS_QA_STATE_BACKEND=lane_d MBOS_QA_GATEWAY_MODE=lane_e (the test sets them). DRY-RUN only; throwaway PostgreSQL."""
import json
import pathlib
import sys
import tempfile
import uuid

import psycopg
from sqlalchemy.engine import make_url

from mbos_qa import impl_spine as I

out: dict = {}
app = I.new_lane_d_database("qa_split")
sysdb = I.new_database("qa_splits")


def as_(url, user):
    return make_url(url).set(username=user, password=None).render_as_string(hide_password=False).replace("+psycopg2", "").replace("+psycopg", "")


sysname = make_url(sysdb).database
with psycopg.connect(app, autocommit=True) as c:
    c.execute("CREATE SCHEMA IF NOT EXISTS dbos AUTHORIZATION mbos_dbos")
with psycopg.connect(sysdb.replace(f"/{sysname}?", "/postgres?"), autocommit=True) as c:
    c.execute(f"ALTER DATABASE {sysname} OWNER TO mbos_dbos")
worker, owner, sysu = as_(app, "mbos_dbos"), as_(app, "mbos_operator_ui"), as_(sysdb, "mbos_dbos")

from mbos.adapters.governance import lane_e_components, role_dsns
from mbos.config import Settings
from mbos.db.engine import engine_for
from mbos.runtime import init_runtime

s = Settings(database_url=worker, system_database_url=sysu, owner_database_url=owner, approval_poll_seconds=0.3,
             state_backend="lane_d", gateway_mode="lane_e")
comps, _ = lane_e_components(role_dsns(worker, owner), I.policy_path())
I._wrap_effector()
rt = init_runtime(s, comps)
out["engine_user"] = rt.engine.connect().exec_driver_sql("select current_user").scalar()

from mbos import spine_d

# the workflow login cannot release the initial FROZEN state; the owner login can
try:
    with rt.engine.begin() as c:
        spine_d.set_kill_switch(c, "global_freeze", False, reason="forged release by the workflow login")
    out["library_release_in_a_process_holding_both_dsns_refused"] = False
except Exception as e:  # noqa: BLE001
    out["library_release_in_a_process_holding_both_dsns_refused"] = type(e).__name__ + ": " + str(e).splitlines()[0][:120]
with engine_for(owner).begin() as c:
    spine_d.set_kill_switch(c, "global_freeze", False, reason="Michael releases the initial FROZEN state")

I._STATE["rt"] = rt
q = I.SpineQA(pathlib.Path(tempfile.mkdtemp(prefix="a07s-")))
item = q.discover()
areq = q.pending(item)
out["pending_state"] = q.item(item)["state"]
# forged approval from the workflow login (what an agent-reachable process could do)
from mbos import workflows
from mbos.runtime import components

try:
    with rt.engine.begin() as c:
        spine_d_mod = I.spine_module()
        spine_d_mod.decide(c, areq["action_request_id"], "YES", areq["payload_hash"], components(), auth_context=I.STEP_UP)
    out["workflow_decide_refused"] = False
except Exception as e:  # noqa: BLE001
    out["workflow_decide_refused"] = type(e).__name__ + ": " + str(e).splitlines()[0][:120]
out["approvals_after_forgery"] = len(q.approvals(areq["action_request_id"]))
out["state_after_forgery"] = q.item(item)["state"]
# the owner decides YES; the parked workflow must wake and execute (dry-run)
dec = q.decide(areq["action_request_id"], "YES")
out["decision_ok"] = bool(dec)
import time

end = time.monotonic() + 60
while time.monotonic() < end and q.areq(areq["action_request_id"])["status"] not in ("executed", "outcome_recorded"):
    time.sleep(0.2)
out["final_item_state"] = q.item(item)["state"]
out["areq_status"] = q.areq(areq["action_request_id"])["status"]
out["approval_written_by_owner"] = len(q.approvals(areq["action_request_id"]))
out["effector_executions"] = sum(I.INVOCATIONS.values())
out["chain_ok"] = bool(q.verify_chain().get("ok", q.verify_chain()))
print("RESULT " + json.dumps(out))
q.close()
