from __future__ import annotations

import sys
from pathlib import Path

import pytest

from python_tofu.exceptions import ConfigError
from python_tofu.loader import load_stack

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = ROOT / "examples" / "gcp_bootstrap" / "infra.py"
CLEAN_EXAMPLE = ROOT / "examples" / "gcp_clean" / "stack.py"


def test_loads_example_config() -> None:
    stack = load_stack(EXAMPLE_CONFIG)
    assert stack.provider.project == "example-bootstrap"
    assert stack.projects[0].project_id == "example-bootstrap"
    assert len(stack.buckets) == 1


def test_loads_mapping_stack(tmp_path: Path) -> None:
    path = tmp_path / "infra.py"
    path.write_text(
        """\
stack = {
    "provider": {"project": "demo-project"},
    "projects": [{"project_id": "demo-project", "name": "Demo"}],
}
""",
        encoding="utf-8",
    )
    stack = load_stack(path)
    assert stack.projects[0].name == "Demo"


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_stack(tmp_path / "missing.py")


def test_non_python_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "infra.yaml"
    path.write_text("provider: {}\n")
    with pytest.raises(ConfigError, match="must be a .py module"):
        load_stack(path)


def test_missing_stack_raises(tmp_path: Path) -> None:
    path = tmp_path / "infra.py"
    path.write_text("value = 1\n")
    with pytest.raises(ConfigError, match="must define"):
        load_stack(path)


def test_import_error_is_wrapped(tmp_path: Path) -> None:
    path = tmp_path / "infra.py"
    path.write_text("raise RuntimeError('boom')\n")
    with pytest.raises(ConfigError, match="boom"):
        load_stack(path)


def test_wrong_stack_type_raises(tmp_path: Path) -> None:
    path = tmp_path / "infra.py"
    path.write_text("stack = 42\n")
    with pytest.raises(ConfigError, match="must expose a `stack`"):
        load_stack(path)


def test_loads_split_example_stack() -> None:
    stack = load_stack(CLEAN_EXAMPLE)
    assert stack.provider.project == "acme-platform"
    assert [bucket.name for bucket in stack.buckets] == [
        "acme-platform-artifacts",
        "acme-platform-model-cache",
    ]
    assert [account.account_id for account in stack.service_accounts] == [
        "ci-runner",
        "readonly-audit",
    ]


def test_config_can_import_sibling_packages(tmp_path: Path) -> None:
    parts = tmp_path / "sibling_parts"
    parts.mkdir()
    (parts / "__init__.py").write_text("", encoding="utf-8")
    (parts / "resources.py").write_text(
        """\
from python_tofu import StorageBucket

BUCKETS = [StorageBucket(project="demo-project", name="demo-sibling")]
""",
        encoding="utf-8",
    )
    path = tmp_path / "infra.py"
    path.write_text(
        """\
from python_tofu import GcpProvider, GcpStack
from sibling_parts.resources import BUCKETS

stack = GcpStack(provider=GcpProvider(project="demo-project"), buckets=BUCKETS)
""",
        encoding="utf-8",
    )

    stack = load_stack(path)
    assert [bucket.name for bucket in stack.buckets] == ["demo-sibling"]
    assert str(tmp_path) not in sys.path


def test_config_can_use_relative_imports(tmp_path: Path) -> None:
    parts = tmp_path / "relative_parts"
    parts.mkdir()
    (parts / "__init__.py").write_text("", encoding="utf-8")
    (parts / "resources.py").write_text(
        """\
from python_tofu import StorageBucket

BUCKETS = [StorageBucket(project="demo-project", name="demo-relative")]
""",
        encoding="utf-8",
    )
    path = tmp_path / "infra.py"
    path.write_text(
        """\
from python_tofu import GcpProvider, GcpStack
from .relative_parts.resources import BUCKETS

stack = GcpStack(provider=GcpProvider(project="demo-project"), buckets=BUCKETS)
""",
        encoding="utf-8",
    )

    stack = load_stack(path)
    assert [bucket.name for bucket in stack.buckets] == ["demo-relative"]
    assert str(tmp_path) not in sys.path
