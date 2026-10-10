"""F-56: the REAL rendered Save form must submit cat, row1-row4 and condition (F-54 `_save()` dropped them)."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urlencode

from operator_ui import market_search as ms
from tests.conftest import PIN
from tests.test_market_f47 import cache, get, post, ui  # noqa: F401
from tests.test_operator_ui import req

CHOICES = dict(go=1, keywords="trailer", base="Conway AR", radius="120", min_price="100", max_price="500", cat="trailers", row1="tools", row2="trailers",
               row3="", row4="", condition="used", broad=1)


class _Forms(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms, self.cur = [], None

    def handle_starttag(self, tag, a):
        a = dict(a)
        if tag == "form":
            self.cur = {"action": a.get("action"), "fields": {}}
            self.forms.append(self.cur)
        elif tag == "input" and self.cur is not None and a.get("name"):
            self.cur["fields"][a["name"]] = a.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.cur = None


def _row(h, i):
    import re
    m = re.search(rf"<select name='row{i}'>(.*?)</select>", h)
    return re.search(r"<option value='([^']*)' selected>", m.group(1)).group(1)


def _save_form(html: str) -> dict:
    p = _Forms()
    p.feed(html)
    return next(f for f in p.forms if f["action"] == "/market/save")


def test_real_save_form_submits_cat_rows_and_condition(ui):
    f = _save_form(get(ui, **CHOICES))["fields"]
    assert f["cat"] == "trailers" and f["condition"] == "used"
    assert (f["row1"], f["row2"], f["row3"], f["row4"]) == ("tools", "trailers", "", "")
    assert float(f["min_price"]) == 100 and float(f["max_price"]) == 500 and f["broad"] == "1"


def _fresh_app_on(ui, tmp_path):
    """New App (no shared memory) reading the SAME campaigns file as `ui`."""
    import threading
    from http.server import ThreadingHTTPServer
    from operator_ui.server import App, make_handler
    from tests.test_market_f47 import GOV_POLICY, StubStore
    app = App(StubStore(), operator_pin=PIN, campaigns_file=str(tmp_path / "campaigns.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    app.port = httpd.server_address[1]
    return app, httpd


def test_real_save_reopen_and_restart_keep_them(ui, tmp_path):
    form = _save_form(get(ui, **CHOICES))
    fields = {k: v for k, v in form["fields"].items() if k not in ("csrf", "nonce", "pin", "title")}      # pin and title are typed by the owner
    st, loc, _ = post(ui, "/market/save", **{**fields, "title": "f56"})       # the fields exactly as the browser would submit them
    assert st == 303 and "created" in loc
    nice = ui.campaign_records()[0]["doc"]["criteria"]["nice_to_have"]
    assert "cat:trailers" in nice and "rows:tools>trailers>>" in nice and "cond:used" in nice
    cid = ui.campaign_records()[0]["doc"]["campaign_id"]

    def check(h):
        assert "Min price: $100" in h and "Max price: $500" in h and "Condition: used" in h and "Mode: BROAD" in h and "filter-errors" not in h
        assert "name='cat' value='trailers'" in h and _row(h, 1) == "tools" and _row(h, 2) == "trailers" and _row(h, 3) == ""
    check(get(ui, run=cid))                                                       # reopen
    app2, httpd2 = _fresh_app_on(ui, tmp_path)                                      # restart: new process state, same campaigns file
    try:
        assert app2.campaign_records()[0]["doc"]["campaign_id"] == cid
        check(req(app2, "GET", "/market?" + urlencode({"run": cid}))[2])
    finally:
        httpd2.shutdown()
        httpd2.server_close()


def test_two_checked_categories_survive_the_save_form(ui):
    h = get(ui, go=1, keywords="x", max_price="500", cat="equipment")
    f = _save_form(h)["fields"]
    f["cat"] = "equipment,tools"                                                  # what the hidden field holds when two boxes are checked
    from operator_ui import market_view as mv
    assert "cat:equipment>tools" in mv.save_form({**f, "csrf": "x"})["nice_to_have"]
