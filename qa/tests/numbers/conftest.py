"""G-16: the F-22 "My numbers" page, driven over real HTTP against lane D's REAL schema, connecting as the real Operator UI login
(`mbos_operator_ui`, role `approver`, non-superuser). Operator UI code (06 @ lane_f_06_numbers) and lane D (04 @ lane_d_04_numbers)
come from `git archive` into temp dirs; nothing is installed or merged."""
from __future__ import annotations

import http.client
import io
import json
import pathlib
import subprocess
import sys
import tarfile
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import unquote, urlencode

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

QA = pathlib.Path(__file__).resolve().parents[2]
REPO = QA.parent
PIN = "4321"
_n = iter(range(10**9))


@pytest.fixture(scope="session")
def ui_src(tmp_path_factory):
    sha = json.loads((QA / "impl_lane_pins.json").read_text())["lane_f_06_numbers"]
    d = tmp_path_factory.mktemp("ui06")
    tar = subprocess.run(["git", "archive", sha, "operator_ui"], cwd=REPO, capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(d, filter="data")
    sys.path.insert(0, str(d))
    for m in [m for m in sys.modules if m.startswith("operator_ui")]:
        del sys.modules[m]
    yield d
    sys.path.remove(str(d))


@pytest.fixture(scope="session")
def db():
    from mbos_qa import impl_spine

    url = impl_spine.new_lane_d_database("qa_num", pin="lane_d_04_numbers")
    owner = sa.create_engine(url)
    yield url, owner
    owner.dispose()


def login(url, role):
    return sa.create_engine(make_url(url).set(username=role, password=None))


@pytest.fixture(scope="session")
def ui(ui_src, db):
    from mbos.runtime import Components

    from operator_ui.backend import SpineBackend
    from operator_ui.server import App, make_handler

    url, _ = db
    eng = login(url, "mbos_operator_ui")
    app = App(SpineBackend(eng, Components(), lane="lane_d"), operator_pin=PIN)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    app.port = httpd.server_address[1]
    yield app
    httpd.shutdown()
    httpd.server_close()
    eng.dispose()


def req(ui, method, path, form=None, host=None, raw=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", ui.port, timeout=20)
    body = raw if raw is not None else (urlencode(form, encoding="utf-8") if form else None)
    hdr = {"Host": host or f"127.0.0.1:{ui.port}", **(headers or {})}
    if body is not None:
        hdr["Content-Type"] = "application/x-www-form-urlencoded"
    c.request(method, path, body=body, headers=hdr)
    r = c.getresponse()
    return r.status, unquote(r.getheader("Location") or ""), r.read().decode("utf-8", "replace")


def post(ui, path, **f):
    f = {"csrf": ui.csrf, "pin": PIN, "nonce": f"nonce{next(_n):08d}", **f}
    return req(ui, "POST", path, f)


def position(owner):
    with owner.connect() as c:
        r = c.execute(sa.text("SELECT protected_principal, earned_working_capital, realized_profit FROM mbos.v_capital_position "
                              "WHERE mode='dry_run'")).first()
    return tuple(float(x) for x in r) if r else (0.0, 0.0, 0.0)


def counts(owner):
    with owner.connect() as c:
        return (c.scalar(sa.text("SELECT count(*) FROM mbos.receipts")), c.scalar(sa.text("SELECT count(*) FROM mbos.mission")),
                c.scalar(sa.text("SELECT count(*) FROM mbos.capital_ledger")))


def mission(ui):
    return ui.store.my_numbers()["mission"]
