"""A-10: a NON-editable wheel install works with no environment variables (contracts + operator profile are packaged)."""

import subprocess
import sys

import pytest

from tests.helpers.common import ROOT


@pytest.mark.slow_build
def test_wheel_install_finds_contracts_and_profile(tmp_path):
    uv = ROOT / ".tools" / "uv"
    if not uv.exists():
        pytest.skip("project-local uv not available")
    wheel_dir, venv = tmp_path / "wheel", tmp_path / "venv"
    subprocess.run([str(ROOT / ".venv/bin/python"), "-m", "pip", "--version"], capture_output=True)
    env = {"UV_CACHE_DIR": str(ROOT / ".tools/uv-cache"), "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    r = subprocess.run([str(uv), "build", "--wheel", "--out-dir", str(wheel_dir), str(ROOT)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr[-1500:]
    whl = next(wheel_dir.glob("mbos-*.whl"))
    subprocess.run([str(uv), "venv", "-q", "--python", "3.12", str(venv)], check=True, env={**env, "UV_PYTHON_INSTALL_DIR": str(ROOT / ".tools/python")})
    subprocess.run([str(uv), "pip", "install", "-q", "--python", str(venv / "bin/python"), str(whl)], check=True, env=env)
    code = ("from mbos.contracts import schemas; from mbos import card; import json\n"
            "assert 'item' in schemas._load()[0] and 'card' in schemas._load()[0]\n"
            "p = card.load_profile(); assert p['transport']['trailer_owned'] is False\n"
            "print('packaged-ok', schemas.contracts_dir())")
    r = subprocess.run([str(venv / "bin/python"), "-I", "-c", code], capture_output=True, text=True, cwd=str(tmp_path),
                       env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 0 and "packaged-ok" in r.stdout and "_data" in r.stdout, r.stdout + r.stderr[-1500:]
