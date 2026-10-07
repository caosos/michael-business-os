"""D-15: provision() — after one superuser call, workers run as the real mbos_dbos login with no superuser."""

import psycopg
import pytest
from psycopg import errors

from mbos_state.provision import provision
from conftest import key

N = iter(range(10_000))


@pytest.fixture
def provisioned(cluster):
    n = next(N)
    admin = f"{cluster['base']} dbname=postgres user=postgres"
    p = provision(admin, app_db=f"prov_app_{n}", sys_db=f"prov_sys_{n}")
    yield admin, p
    with psycopg.connect(admin, autocommit=True) as c:
        for db in (f"prov_app_{n}", f"prov_sys_{n}"):
            c.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")


def test_login_runs_the_spine_without_superuser(provisioned):
    admin, p = provisioned
    assert p.login == "mbos_dbos" and "0013" in p.migrations_applied
    with psycopg.connect(p.app_conninfo, autocommit=True) as c:
        assert c.execute("SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user").fetchone() \
            == ("mbos_dbos", False)
        pid = c.execute("""SELECT mbos.record_provenance('{"actor_type":"system","basis":"FACT",
                           "tool_name":"t","tool_version":"1"}')""").fetchone()[0]
        item = c.execute("SELECT mbos.create_item(%s::jsonb, '{\"type\":\"system\",\"id\":\"spine\"}', 'x', %s, %s)",
                         ('{"type":"flip","category":"trailer","dedup_key":"d","sources":[],"normalized":{}}', [pid],
                          key())).fetchone()[0]
        assert item.startswith("itm_")
        c.execute("CREATE TABLE dbos.transaction_outputs (k text)")                   # owns the checkpoint schema
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("CREATE TABLE mbos.sneaky (x int)")                             # but not the state schema
        with pytest.raises(psycopg.Error):
            c.execute("UPDATE mbos.receipts SET intent = 'x'")
        c.execute("SELECT mbos.panic_set('L3', NULL, false, '{\"type\":\"human\",\"id\":\"michael\"}', 'release', %s, %s)",
                  ([pid], key()))                                                      # approver membership
        assert c.execute("SELECT 1 FROM mbos_ext.vector_dims('[1,2,3]'::mbos_ext.vector)").fetchone()
    with psycopg.connect(p.sys_conninfo, autocommit=True) as c:                        # its own DBOS system DB
        c.execute("CREATE TABLE workflow_status (id text)")


def test_idempotent_and_urls(provisioned, cluster):
    admin, p = provisioned
    again = provision(admin, app_db=p.app_conninfo.split("dbname=")[1].split()[0],
                      sys_db=p.sys_conninfo.split("dbname=")[1].split()[0])
    assert again.migrations_applied == [] and again.app_url == p.app_url
    assert p.app_url.startswith("postgresql://mbos_dbos@/prov_app_") and "host=" in p.app_url


def test_refuses_without_superuser(cluster):
    with pytest.raises(PermissionError):
        provision(f"{cluster['base']} dbname=postgres user=mbos_reader", app_db="nope_app")


def test_url_is_usable_by_libpq(provisioned):
    _, p = provisioned
    with psycopg.connect(p.app_url) as c:                     # the URL form (SQLAlchemy/DBOS config) connects too
        assert c.execute("SELECT current_user").fetchone()[0] == "mbos_dbos"
