"""Ship the frozen contracts and the operator profile INSIDE the wheel, copied at build time from their single
source files (docs/research/contracts, config/), so a non-editable install works with no environment variable and
the copy can never drift from the source."""

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent


class BuildWithData(build_py):
    def run(self):
        super().run()
        dest = Path(self.build_lib) / "mbos" / "_data"
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(ROOT / "docs" / "research" / "contracts", dest / "contracts",
                        ignore=shutil.ignore_patterns("__pycache__", "examples"))
        shutil.copytree(ROOT / "config", dest / "config", ignore=shutil.ignore_patterns("__pycache__"))


setup(cmdclass={"build_py": BuildWithData})
