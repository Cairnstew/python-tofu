from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = ROOT / "examples" / "gcp_bootstrap" / "infra.py"

ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "python_tofu", *args],
        capture_output=True,
        text=True,
        env=ENV,
    )


def test_module_help_exits_zero() -> None:
    result = _run("--help")
    assert result.returncode == 0
    assert "Usage" in result.stdout


def test_module_render_writes_files(tmp_path: Path) -> None:
    result = _run("render", "--config", str(EXAMPLE_CONFIG), "--workdir", str(tmp_path))
    assert result.returncode == 0, result.stderr
    for name in ("versions.tf", "providers.tf", "main.tf"):
        assert (tmp_path / name).is_file()


def test_module_rejects_missing_config(tmp_path: Path) -> None:
    result = _run("render", "--config", str(tmp_path / "nope.py"), "--workdir", str(tmp_path))
    assert result.returncode == 1
    assert "not found" in result.stderr
