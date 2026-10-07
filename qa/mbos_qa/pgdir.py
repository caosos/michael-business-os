"""Where this lane's throwaway PostgreSQL clusters live, and how they are always cleaned up.

Lesson (2026-10-07): clusters under /run/user/1001 (a 1.5 GB tmpfs shared by every agent) filled it to 100% after
hard-killed runs left ~1 GB behind, which blocked every other agent's Postgres start. Rules now:
  * data lives on DISK under a SHORT /tmp path (Unix socket paths must stay under 107 bytes, so not the scratchpad);
  * every cluster is stopped and deleted by `release()` in a `finally`/fixture teardown and, as a backstop, atexit;
  * on startup, leftovers of dead runs (owner pid gone) are stopped and removed (`sweep()`), only ours (`a07pg-*`).
"""
from __future__ import annotations

import atexit
import os
import pathlib
import shutil
import signal
import tempfile
import time

ROOT = pathlib.Path(os.environ.get("MBOS_QA_PG_ROOT", "/tmp"))
PREFIX = "a07pg-"
_made: list[pathlib.Path] = []


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _stop_cluster(d: pathlib.Path) -> None:
    pidfile = d / "postmaster.pid"
    if pidfile.exists():
        try:
            pm = int(pidfile.read_text().splitlines()[0])
            if _alive(pm):
                os.kill(pm, signal.SIGINT)  # fast shutdown
                for _ in range(100):
                    if not _alive(pm):
                        break
                    time.sleep(0.1)
        except (ValueError, OSError):
            pass


def sweep() -> list[str]:
    """Stop and delete clusters of runs whose owner process is gone. Only `a07pg-<pid>-*` under ROOT."""
    gone = []
    for d in ROOT.glob(f"{PREFIX}*"):
        try:
            owner = int(d.name[len(PREFIX):].split("-")[0])
        except ValueError:
            continue
        if owner != os.getpid() and not _alive(owner):
            _stop_cluster(d)
            shutil.rmtree(d, ignore_errors=True)
            gone.append(str(d))
    return gone


def make(tag: str = "") -> pathlib.Path:
    sweep()
    d = pathlib.Path(tempfile.mkdtemp(prefix=f"{PREFIX}{os.getpid()}-{tag}", dir=ROOT))
    _made.append(d)
    return d


def release(d: pathlib.Path) -> None:
    _stop_cluster(d)
    shutil.rmtree(d, ignore_errors=True)
    if d in _made:
        _made.remove(d)


def _release_all() -> None:
    for d in list(_made):
        release(d)


atexit.register(_release_all)
