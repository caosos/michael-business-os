import sys
import types

import pytest

from mbos import cli
from mbos.config import Settings


def test_owner_engine_uses_owner_url_when_set_and_warns_when_not(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "_engine", lambda: ("worker-engine",))
    monkeypatch.setattr("mbos.config.settings", lambda: Settings(database_url="postgresql://w/x", system_database_url="postgresql://w/y"))
    assert cli._owner_engine() == ("worker-engine",)
    assert "MBOS_OWNER_DATABASE_URL is not set" in capsys.readouterr().err

    fake_engine = object()
    monkeypatch.setattr("mbos.config.settings", lambda: Settings(database_url="postgresql://w/x", system_database_url="postgresql://w/y",
                                                                 owner_database_url="postgresql://o/x"))
    monkeypatch.setattr("mbos.db.engine.engine_for", lambda url: (calls.append(url), fake_engine)[1])
    monkeypatch.setattr("mbos.db.migrate.migrate", lambda e: None)
    assert cli._owner_engine() is fake_engine and calls == ["postgresql://o/x"]
    assert capsys.readouterr().err == ""


def test_human_commands_use_the_owner_engine():
    import inspect
    for fn in (cli.cmd_decide, cli.cmd_outcome, cli.cmd_panic):
        assert "_owner_engine()" in inspect.getsource(fn), fn.__name__
    assert "_owner_engine()" in inspect.getsource(cli.cmd_note)
    assert "_owner_engine()" not in inspect.getsource(cli.cmd_queue)     # reading the queue needs no owner rights
