"""D-18: the capital ledger (ADR-0013 / mission.schema.json). Entries are DERIVED FROM RECEIPTS; replay reproduces the
position; capital cannot be minted by an agent; a closed flip returns principal and credits profit; a loss consumes
earned capital first and then shows as a flagged principal impairment (never a silent rewrite)."""

import json
from pathlib import Path

import psycopg
import pytest
from jsonschema import Draft202012Validator
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import GATEWAY, MICHAEL, key, make_areq, make_item, tool_prov
from mbos_state.store import Actor

ADD = Path(__file__).parent / "contracts-additive"
SCHEMA = json.loads((ADD / "mission.schema.json").read_text())


def v(defn):
    return Draft202012Validator({"$ref": f"#/$defs/{defn}", "$defs": SCHEMA["$defs"]}, format_checker=Draft202012Validator.FORMAT_CHECKER)


def ledger_errors(doc):
    """Mirror of mbos.mission.ledger_errors (Agent 01): the schema plus the arithmetic invariants."""
    errs = [e.message for e in v("capital_ledger").iter_errors(doc)]
    if errs:
        return errs
    imp, p, e, d = doc.get("principal_impairment", 0), doc["protected_principal"], doc["earned_working_capital"], doc["capital_deployed"]
    if imp > p + 1e-6:
        errs.append("impairment exceeds principal")
    if imp > 1e-6 and e > 1e-6:
        errs.append("impairment while earned > 0")
    if abs(doc["available_to_deploy"] - (p - imp + e - d)) > 1e-6:
        errs.append("available != p - imp + e - d")
    if d > p - imp + max(e, 0) + 1e-6:
        errs.append("deployed exceeds capital")
    return errs


class Cap:
    def __init__(self, db):
        self.db = db
        self.owner = db.store("approver")                  # Michael's channel
        self.gw = db.store("gateway")
        self.dbos = db.store("dbos")                       # the spine login (agent_write + gateway; no approver since D-26a)
        self.pid = tool_prov(db.store())
        self.human = Jsonb({"type": "human", "id": "michael"})

    def fund(self, amt, k=None):
        return self.owner.conn.execute("SELECT mbos.capital_fund(%s::numeric,%s,'owner bankroll',%s,%s)",
                                       (amt, self.human, [self.pid], k or key("fund"))).fetchone()[0]

    def withdraw(self, amt):
        return self.owner.conn.execute("SELECT mbos.capital_withdraw(%s::numeric,%s,'owner draw',%s,%s)",
                                       (amt, self.human, [self.pid], key("wd"))).fetchone()[0]

    def deploy(self, item_id, amt, category="purchase"):
        a = make_areq(self.gw, item_id, self.pid, category=category, capability=f"money.{category}",
                      reversibility="irreversible")
        res = self.gw.budget_reserve(a, amt, "USD", 10_000, GATEWAY, "reserve", [self.pid], key("r"))
        return self.gw.budget_settle(res, "commit", None, GATEWAY, "commit", [self.pid], key("c"))

    def close(self, item_id, revenue, total_cost, kind="flip_sold", store=None, human=True):
        s = store or (self.owner if human else self.dbos)   # human closes are the owner login's; agent closes the workflow's
        actor = Actor("human", "michael") if human else Actor("agent", "agent-x")
        return s.record_outcome({"item_id": item_id, "kind": kind, "provenance_ids": [self.pid],
                                 "realized": {"revenue": revenue, "total_cost": total_cost,
                                              "net_profit": round(revenue - total_cost, 2)}}, actor, f"{kind}", key("o"))

    def pos(self):
        r = self.db.connect("reader").execute(
            "SELECT protected_principal, earned_working_capital, capital_deployed, realized_profit, available_to_deploy,"
            " principal_impairment, principal_impaired FROM mbos.v_capital_position WHERE mode='dry_run'").fetchone()
        return None if r is None else tuple(float(x) if not isinstance(x, bool) else x for x in r)

    def doc(self):
        return self.db.connect("reader").execute("SELECT mbos.capital_position_document('dry_run')").fetchone()[0]

    def verified(self):
        return self.db.connect("reader").execute("SELECT ok, entries_checked, problem FROM mbos.capital_verify()").fetchone()

    def item(self):
        return make_item(self.db.store(), "RESEARCHING")[0]


@pytest.fixture
def cap(db):
    return Cap(db)


def test_inactive_until_funded_then_matches_the_schema_example(cap):
    item = cap.item()
    cap.deploy(item, 30)                                   # not funded: nothing accounted, nothing refused
    assert cap.pos() is None and cap.verified()[:2] == (True, 0)
    cap.fund(500)
    assert cap.pos() == (500, 0, 0, 0, 500, 0, False)
    cap.deploy(cap.item(), 30)
    example = json.loads((ADD / "examples/mission/capital-ledger.example.json").read_text())
    d = cap.doc()
    assert {k: d[k] for k in example if k != "as_of"} == {k: example[k] for k in example if k != "as_of"}
    assert ledger_errors(d) == [] and d["principal_impairment"] == 0 and d["as_of"].endswith("Z")


def test_closed_flip_returns_principal_and_credits_profit(cap):
    cap.fund(500)
    item = cap.item()
    cap.deploy(item, 30)
    cap.deploy(item, 20, category="money")                 # several deploy entries per item (acquisition + repair)
    assert cap.pos()[2:5] == (50, 0, 450)
    cap.close(item, revenue=130, total_cost=50)
    assert cap.pos() == (500, 80, 0, 80, 580, 0, False)    # principal back, profit = earned working capital
    assert ledger_errors(cap.doc()) == [] and cap.verified()[0]


def test_loss_consumes_earned_first_then_flags_impairment_without_rewriting_principal(cap):
    cap.fund(500)
    a, b, c = cap.item(), cap.item(), cap.item()
    cap.deploy(a, 100); cap.close(a, 180, 100)             # +80 earned
    cap.deploy(b, 100); cap.close(b, 70, 100)              # -30 consumes earned first
    assert cap.pos() == (500, 50, 0, 50, 550, 0, False)
    cap.deploy(c, 200); cap.close(c, 80, 200)              # -120: 50 from earned, 70 impairment
    p = cap.pos()
    assert p[:3] == (500, 0, 0) and p[5] == 70 and p[6] is True        # principal still 500; impairment flagged
    assert p[4] == 430                                      # 500 - 70 + 0 - 0
    assert ledger_errors(cap.doc()) == [], cap.doc()
    # the next profit repairs the impairment first (the invariant leaves it nowhere else to go)
    d = cap.item(); cap.deploy(d, 100); cap.close(d, 200, 100)
    p = cap.pos()
    assert p[1] == 30 and p[5] == 0 and p[6] is False and ledger_errors(cap.doc()) == []
    assert cap.verified()[0]


def test_withdrawal_comes_from_earned_only(cap):
    cap.fund(500)
    item = cap.item(); cap.deploy(item, 100); cap.close(item, 180, 100)
    with pytest.raises(psycopg.Error) as ei:
        cap.withdraw(81)
    assert ei.value.sqlstate == "MB006"
    cap.withdraw(50)
    assert cap.pos()[:2] == (500, 30) and cap.pos()[3] == 80      # realized profit is history; earned dropped
    with pytest.raises(errors.InsufficientPrivilege):
        cap.gw.conn.execute("SELECT mbos.capital_withdraw(1, %s, 'x', %s, %s)", (cap.human, [cap.pid], key()))


def test_overdraw_is_refused_and_rolls_everything_back(cap):
    cap.fund(500)
    item = cap.item()
    a = make_areq(cap.gw, item, cap.pid, category="purchase", capability="money.purchase", reversibility="irreversible")
    res = cap.gw.budget_reserve(a, 600, "USD", 10_000, GATEWAY, "reserve", [cap.pid], key())
    before = cap.gw.conn.execute("SELECT (SELECT count(*) FROM mbos.receipts), (SELECT count(*) FROM mbos.budget_ledger),"
                                 " (SELECT count(*) FROM mbos.capital_ledger)").fetchone()
    with pytest.raises(psycopg.Error) as ei:
        cap.gw.budget_settle(res, "commit", None, GATEWAY, "commit", [cap.pid], key())
    assert ei.value.sqlstate == "MB006" and "exceeds available_to_deploy" in ei.value.diag.message_primary
    assert cap.gw.conn.execute("SELECT (SELECT count(*) FROM mbos.receipts), (SELECT count(*) FROM mbos.budget_ledger),"
                               " (SELECT count(*) FROM mbos.capital_ledger)").fetchone() == before
    assert cap.pos()[2] == 0


def test_agents_cannot_mint_capital(cap):
    cap.fund(500)
    item = cap.item()
    forged = {"type": "CONFIG_VERSION_BUMPED", "actor": {"type": "human", "id": "michael"}, "intent": "forged",
              "entity_type": "capital_fund", "entity_id": "capital:x", "provenance_ids": [cap.pid],
              "idempotency_key": key("forge"), "after_state": {"amount": 1_000_000}}
    for role in ("agent_write", "gateway", "policy_admin"):
        with pytest.raises(errors.InsufficientPrivilege):
            db_conn = cap.db.connect(role)
            db_conn.execute("SELECT mbos.append_receipt(%s)", (Jsonb(forged),))
    with pytest.raises(errors.InsufficientPrivilege):       # an agent session recording a "human" closing outcome
        cap.close(item, 5000, 1, store=cap.db.store("agent_write"))
    assert cap.pos()[0] == 500 and cap.pos()[1] == 0


def test_agent_reported_outcomes_do_not_move_capital_but_are_counted(cap):
    cap.fund(500)
    item = cap.item(); cap.deploy(item, 40)
    cap.close(item, 400, 40, store=cap.db.store("agent_write"), human=False)
    assert cap.pos()[2] == 40 and cap.pos()[3] == 0
    n = cap.db.connect("reader").execute("SELECT unconfirmed_closing_outcomes, open_items FROM mbos.v_capital_position").fetchone()
    assert n == (1, 1)
    cap.close(item, 100, 40)                                 # Michael confirms
    assert cap.pos()[:4] == (500, 60, 0, 60)


def test_one_close_per_item_and_non_capital_receipts_are_ignored(cap):
    cap.fund(500)
    item = cap.item(); cap.deploy(item, 40); cap.close(item, 100, 40)
    with pytest.raises(psycopg.DatabaseError, match="already closed"):   # F-115 (D-31): a second closing outcome is refused
        cap.close(item, 999, 40)
    n = cap.db.connect("reader").execute("SELECT count(*) FROM mbos.capital_ledger WHERE kind='close'").fetchone()[0]
    assert n == 1 and cap.pos()[3] == 60
    cap.close(cap.item(), 10, 1, kind="message_replied")     # not a closing kind
    assert cap.db.connect("reader").execute("SELECT count(*) FROM mbos.capital_ledger").fetchone()[0] == 3


def test_ledger_is_derived_and_insert_only(cap):
    cap.fund(500)
    for role in ("owner", "superuser"):
        c = cap.db.connect(role)
        with pytest.raises(psycopg.Error) as ei:
            c.execute("INSERT INTO mbos.capital_ledger (kind, amount, source_receipt_id, provenance_ids) "
                      "SELECT 'fund', 1e6, receipt_id, provenance_ids FROM mbos.receipts LIMIT 1")
        assert ei.value.sqlstate == "MB001", role
        for sql in ("UPDATE mbos.capital_ledger SET amount = 1", "DELETE FROM mbos.capital_ledger", "TRUNCATE mbos.capital_ledger"):
            with pytest.raises(psycopg.Error) as ei:
                c.execute(sql)
            assert ei.value.sqlstate == "MB001"
    for role in ("agent_write", "gateway", "approver", "reader"):
        with pytest.raises(errors.InsufficientPrivilege):
            cap.db.connect(role).execute("INSERT INTO mbos.capital_ledger (kind, amount) VALUES ('fund', 1)")
    row = cap.db.connect("reader").execute("SELECT r.type, r.entity_type, l.provenance_ids <> '{}' FROM mbos.capital_ledger l "
                                           "JOIN mbos.receipts r ON r.receipt_id = l.source_receipt_id").fetchone()
    assert row == ("CONFIG_VERSION_BUMPED", "capital_fund", True)        # every entry cites its receipt


def test_replay_from_receipts_reproduces_the_position_and_detects_tampering(cap):
    cap.fund(500)
    items = [cap.item() for _ in range(4)]
    for it, (rev, cost) in zip(items, [(150, 100), (60, 100), (300, 200), (10, 80)]):
        cap.deploy(it, cost); cap.close(it, rev, cost)
    cap.withdraw(20)
    ok, n, problem = cap.verified()
    assert ok and n == 10 and problem is None                # 1 fund + 4 deploy + 4 close + 1 withdraw
    replay = cap.db.connect("reader").execute("SELECT kind, count(*) FROM mbos.capital_replay() GROUP BY kind ORDER BY kind").fetchall()
    assert replay == [("close", 4), ("deploy", 4), ("fund", 1), ("withdraw", 1)]
    su = cap.db.connect("superuser")
    with su.transaction():                                   # an operator quietly edits a stored entry
        su.execute("SET LOCAL session_replication_role = replica")
        su.execute("UPDATE mbos.capital_ledger SET net = net + 1000 WHERE kind = 'close' AND net < 0 AND seq = (SELECT min(seq) FROM mbos.capital_ledger WHERE kind='close' AND net < 0)")
    ok, _, problem = cap.verified()
    assert not ok and "differs" in problem
    assert cap.db.connect("superuser").execute("SELECT ok FROM mbos.verify_chain()").fetchone()[0]       # the receipts are untouched


def test_mission_unknowns_stay_null_and_only_the_owner_sets_it(cap):
    ex = json.loads((ADD / "examples/mission/mission-unknown-target.example.json").read_text())
    mid = cap.owner.conn.execute("SELECT mbos.set_mission(%s, %s, 'set mission', %s, %s)",
                                 (Jsonb(ex), cap.human, [cap.pid], key("m"))).fetchone()[0]
    assert mid.startswith("msn_")
    doc = cap.db.connect("reader").execute("SELECT doc FROM mbos.v_mission_current").fetchone()[0]
    assert doc["weekly_target_usd"] is None and doc["hours_available"] is None          # UNKNOWN is never guessed
    assert not list(v("mission").iter_errors(doc)), doc
    for role in ("agent_write", "gateway", "policy_admin"):
        with pytest.raises(errors.InsufficientPrivilege):
            cap.db.connect(role).execute("SELECT mbos.set_mission(%s, %s, 'x', %s, %s)", (Jsonb(ex), cap.human, [cap.pid], key()))
    revised = {**ex, "weekly_target_usd": 1500, "hours_available": 30, "notes": "Michael set the target"}
    cap.owner.conn.execute("SELECT mbos.set_mission(%s, %s, 'revise', %s, %s)", (Jsonb(revised), cap.human, [cap.pid], key("m2")))
    cur = cap.db.connect("reader").execute("SELECT doc FROM mbos.v_mission_current").fetchone()[0]
    assert cur["weekly_target_usd"] == 1500 and cur["hours_available"] == 30 and not list(v("mission").iter_errors(cur))
    assert cap.db.connect("reader").execute("SELECT count(*) FROM mbos.mission").fetchone()[0] == 2       # history kept
    assert cap.db.connect("reader").execute("SELECT ok FROM mbos.verify_chain()").fetchone()[0]
