#!/usr/bin/env python3
"""Install the built wheel and run the packaged tests from the source archive.

Run after `uv build`: `uv run python scripts/check_distribution.py dist`.
Nothing is imported from the working checkout or an editable installation.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def run(*command: str, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def check_distribution(dist: Path) -> None:
    wheels = sorted(dist.glob("*.whl"))
    sources = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Use a clean dist directory containing one wheel and one source archive")

    with tempfile.TemporaryDirectory(prefix="ocrs-distribution-") as temporary:
        root = Path(temporary)
        with tarfile.open(sources[0]) as archive:
            archive.extractall(root, filter="data")
        [source] = root.iterdir()
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("VIRTUAL_ENV", None)
        environment = root / "environment"
        env["UV_PROJECT_ENVIRONMENT"] = str(environment)
        run(
            "uv",
            "sync",
            "--locked",
            "--no-install-project",
            "--python",
            sys.executable,
            cwd=source,
            env=env,
        )
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            str(wheels[0]),
            cwd=source,
            env=env,
        )
        # Load the wheel before conftest adds the sdist's src/ to sys.path. Pytest must
        # share this process so ocrs and its submodule search path stay on the wheel.
        run(
            str(python),
            "-c",
            "import ocrs, sys; from pathlib import Path; "
            "assert Path(ocrs.__file__).is_relative_to(Path(sys.prefix)), ocrs.__file__; "
            "print('Testing installed wheel:', ocrs.__file__, flush=True); "
            "import pytest; sys.exit(pytest.main(['-q', 'tests']))",
            cwd=source,
            env=env,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path, help="Directory containing uv build's wheel and sdist")
    check_distribution(parser.parse_args().dist.resolve())
