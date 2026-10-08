import argparse

from mbos import cli
from tests.helpers.seed import seed_flow


def test_items_lists_ids_and_queue_shows_item_id(ledger_db, monkeypatch, capsys):
    ids = seed_flow(ledger_db, act=False)
    monkeypatch.setattr(cli, "_engine", lambda: ledger_db)
    assert cli.cmd_items(argparse.Namespace(state=None, limit=10)) == 0
    out = capsys.readouterr().out
    assert ids["item_id"] in out
    assert cli.cmd_items(argparse.Namespace(state="NO_SUCH_STATE", limit=10)) == 0
    assert "No items." in capsys.readouterr().out
    assert cli.cmd_queue(argparse.Namespace()) == 0
    q = capsys.readouterr().out
    assert f"item    {ids['item_id']}" in q
