import sqlalchemy as sa

from mbos.state_machine import ITEM_TRANSITIONS


def test_python_and_db_item_transitions_identical(ledger_db):
    with ledger_db.connect() as c:
        db = set(c.execute(sa.text("SELECT from_state, to_state FROM mbos.item_state_transitions")).all())
    assert {tuple(r) for r in db} == set(ITEM_TRANSITIONS)


def test_item_schema_states_covered():
    from mbos.contracts import schemas
    states = set(schemas.schema("item")["properties"]["state"]["enum"])
    used = {s for edge in ITEM_TRANSITIONS for s in edge}
    assert used == states
