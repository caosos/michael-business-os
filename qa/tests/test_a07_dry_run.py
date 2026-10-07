"""A7 — in round one and the MVP, 100% of effector receipts have dry_run=true. Audit query: zero exceptions."""
import pytest

from mbos_qa.mocks.governance import GuardDenied

from .conftest import approve, effector_attempts, pending

EFFECTOR_TYPES = ("ACTION_EXECUTED", "ACTION_FAILED")


def dry_run_audit(store) -> tuple[int, list[dict]]:
    """The audit query: every effector receipt, and those that are not dry_run=true."""
    rows = [r for r in store.receipts() if r["type"] in EFFECTOR_TYPES]
    return len(rows), [r for r in rows if (r.get("effector_response") or {}).get("dry_run") is not True]


def test_audit_zero_exceptions_after_full_run(ran):
    total, exceptions = dry_run_audit(ran.store)
    assert total >= 3, "audit must not pass vacuously"
    assert exceptions == []
    for r in ran.store.receipts(type="ACTION_EXECUTED"):
        assert r["details"]["sent"] is False and r["details"]["published"] is False


def test_every_packet_is_labelled_dry_run(ran):
    packets = list((ran.workdir / "packets").glob("*.md"))
    assert len(packets) == len(ran.store.receipts(type="ACTION_EXECUTED"))
    for p in packets:
        assert p.read_text().startswith("# MANUAL-ASSIST PACKET — DRY-RUN")


class LiveEffector:
    """Hostile stand-in: claims to be live."""
    dry_run = False
    effect, tool_name = "send", "live-effector"

    def __init__(self):
        self.calls = 0

    def call_count(self):
        return self.calls

    def lookup(self, key):
        return None

    def execute(self, areq, approval, key):
        self.calls += 1
        return {"provider": "live", "provider_msg_id": "x", "status": "sent", "dry_run": False}


def test_non_dry_run_effector_refused_before_any_call(h):
    live = LiveEffector()
    h.gateway.effectors["comms"] = live
    _, areq = pending(h)
    appr = approve(h, areq)
    with pytest.raises(GuardDenied) as e:
        h.gateway.execute(areq["action_request_id"], appr["approval_id"])
    assert e.value.check == "8-dry-run" and live.calls == 0
    assert dry_run_audit(h.store)[0] == 0


def test_lying_effector_is_caught_and_flagged_by_audit(h):
    class Liar(LiveEffector):
        dry_run = True  # claims dry-run, returns a live response
    liar = Liar()
    h.gateway.effectors["comms"] = liar
    item_id, areq = pending(h)
    appr = approve(h, areq)
    with pytest.raises(GuardDenied):
        h.gateway.execute(areq["action_request_id"], appr["approval_id"])
    total, exceptions = dry_run_audit(h.store)
    assert total == 1 and len(exceptions) == 1, "the audit must surface the violation, not hide it"
    assert exceptions[0]["type"] == "ACTION_FAILED"
    assert h.store.get("item", item_id)["state"] == "FAILED"


def test_mode_is_mvp_by_default(h):
    assert h.gateway.mode in ("round_one", "mvp")
    assert all(e.dry_run for e in h.effectors.values())
    assert effector_attempts(h) == 0


def test_no_network_capable_imports_in_qa_code():
    """Belt and braces for 'nothing leaves the system': the harness itself cannot open a socket."""
    import ast
    import pathlib
    forbidden = {"socket", "smtplib", "urllib", "http", "requests", "httpx", "aiohttp", "ftplib", "telnetlib", "ssl"}
    root = pathlib.Path(__file__).resolve().parent.parent / "mbos_qa"
    hits = []
    for f in root.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                    [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            hits += [f"{f.name}:{n}" for n in names if n.split(".")[0] in forbidden]
    assert hits == []
