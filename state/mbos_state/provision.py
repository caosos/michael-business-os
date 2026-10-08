"""Provision a lane-D database for a real worker login (D-15).

One idempotent call performs every superuser-only step, so that afterwards tests, the DBOS app and other
workers connect as `mbos_dbos` (or another worker login) with NO superuser:

  1. cluster roles (bootstrap/roles.sql)
  2. the app database (owner mbos_owner) and the login's own DBOS system database (owner = login)
  3. in the app DB: pgvector in schema `mbos_ext` (D-08), schema `dbos` owned by the login (DBOS @transaction
     checkpoints live there, in the same transaction as the state write), PUBLIC stripped from `public`
  4. optional passwords for the login and for the owner login `mbos_operator_ui` (scram), set without putting it on any command line
  5. migrations (each one receipted)

Usage (Python):  p = provision(admin_dsn, app_db="mbos_e2e", sys_db="mbos_e2e_sys")
                 engine = sqlalchemy.create_engine(p.app_url)          # as mbos_dbos
CLI:             python -m mbos_state provision --admin-dsn ... --app-db mbos --sys-db mbos_dbos
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlencode

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from . import migrate

ROLES_SQL = Path(__file__).resolve().parent.parent / "bootstrap" / "roles.sql"
OWNER_LOGIN = "mbos_operator_ui"
GROUPS = ("agent_read", "agent_write", "gateway", "approver", "policy_admin", "outbox_relay", "mbos_migrator")


@dataclass(frozen=True)
class Provisioned:
    login: str
    app_conninfo: str          # libpq key=value for the login, app DB
    sys_conninfo: str          # libpq key=value for the login, DBOS system DB
    app_url: str               # postgresql:// URL for the login (SQLAlchemy / DBOS config)
    sys_url: str
    migrations_applied: list[str]
    owner_login: str = "mbos_operator_ui"      # approver + owner_channel: Michael's decisions, notes, capital (D-26a)
    owner_app_conninfo: str = ""
    owner_app_url: str = ""


def _url(conninfo: str) -> str:
    d = conninfo_to_dict(conninfo)
    user = quote(d.get("user", ""), safe="")
    pw = (":" + quote(d["password"], safe="")) if d.get("password") else ""
    host, port, db = d.get("host", ""), d.get("port"), quote(d.get("dbname", ""), safe="")
    query = {}
    if host.startswith("/") or not host:            # unix socket: host goes in the query string
        netloc, query["host"] = f"{user}{pw}@", host or None
        if port:
            query["port"] = port
    else:
        netloc = f"{user}{pw}@{host}" + (f":{port}" if port else "")
    q = urlencode({k: v for k, v in query.items() if v})
    return f"postgresql://{netloc}/{db}" + (f"?{q}" if q else "")


def provision(admin_dsn: str, app_db: str = "mbos", sys_db: str | None = None, login: str = "mbos_dbos",
              password: str | None = None, owner_password: str | None = None, run_migrations: bool = True, log=lambda *_: None) -> Provisioned:
    sys_db = sys_db or f"{app_db}_sys"
    for name in (app_db, sys_db, login):
        if not name.replace("_", "").isalnum():
            raise ValueError(f"unsafe identifier {name!r}")
    with psycopg.connect(admin_dsn, autocommit=True) as su:
        if not su.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]:
            raise PermissionError("provision() needs a superuser connection (it is the only step that does)")
        su.execute(ROLES_SQL.read_text())
        if su.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (login,)).fetchone() is None:
            raise ValueError(f"login {login!r} is not created by roles.sql")
        exists = {r[0] for r in su.execute("SELECT datname FROM pg_database WHERE datname IN (%s, %s)", (app_db, sys_db))}
        if app_db not in exists:
            su.execute(sql.SQL("CREATE DATABASE {} OWNER mbos_owner ENCODING 'UTF8' TEMPLATE template0")
                       .format(sql.Identifier(app_db)))
        if sys_db not in exists:
            su.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0")
                       .format(sql.Identifier(sys_db), sql.Identifier(login)))
        su.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(app_db)))
        su.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(sys_db)))
        su.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(app_db), sql.SQL(", ").join(sql.Identifier(r) for r in (*GROUPS, login))))
        su.execute(sql.SQL("GRANT ALL ON DATABASE {} TO {}").format(sql.Identifier(sys_db), sql.Identifier(login)))
        if password is not None:
            su.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(login), sql.Literal(password)))
        if owner_password is not None:
            su.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(OWNER_LOGIN), sql.Literal(owner_password)))

    app_admin = make_conninfo(admin_dsn, dbname=app_db)
    with psycopg.connect(app_admin, autocommit=True) as su:
        su.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        su.execute("CREATE SCHEMA IF NOT EXISTS mbos_ext")
        su.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA mbos_ext")
        su.execute("GRANT USAGE ON SCHEMA mbos_ext TO agent_read, agent_write, gateway, approver, policy_admin, mbos_owner")
        su.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS dbos AUTHORIZATION {}").format(sql.Identifier(login)))
        su.execute(sql.SQL("ALTER SCHEMA dbos OWNER TO {}").format(sql.Identifier(login)))
    applied = migrate.migrate(app_admin, log=log) if run_migrations else []

    base = {k: v for k, v in conninfo_to_dict(admin_dsn).items() if k not in ("user", "password", "dbname")}
    creds = {"user": login, **({"password": password} if password else {})}
    app_ci = make_conninfo("", **base, **creds, dbname=app_db)
    sys_ci = make_conninfo("", **base, **creds, dbname=sys_db)
    owner_ci = make_conninfo("", **base, user=OWNER_LOGIN, **({"password": owner_password} if owner_password else {}),
                             dbname=app_db)
    return Provisioned(login, app_ci, sys_ci, _url(app_ci), _url(sys_ci), applied, OWNER_LOGIN, owner_ci, _url(owner_ci))
