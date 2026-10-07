from __future__ import annotations

import os
import subprocess
import sys

from tests.helpers.common import ROOT


def run_runner(env_urls: tuple[str, str], *args: str, timeout: float = 90) -> subprocess.CompletedProcess:
    env = {**os.environ, "MBOS_DATABASE_URL": env_urls[0], "MBOS_SYSTEM_DATABASE_URL": env_urls[1]}
    return subprocess.run([sys.executable, "-m", "tests.helpers.runner", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=timeout)


def line(cp: subprocess.CompletedProcess, prefix: str) -> str:
    for ln in cp.stdout.splitlines():
        if ln.startswith(prefix):
            return ln[len(prefix):].strip()
    raise AssertionError(f"no {prefix!r} line.\nSTDOUT:\n{cp.stdout}\nSTDERR:\n{cp.stderr[-3000:]}")
