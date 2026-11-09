from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from python_tofu.models import (  # noqa: E402
    BackendConfig,
    GcpProject,
    GcpProvider,
    GcpStack,
    ProjectApi,
    ProjectIamMember,
    ServiceAccount,
    StorageBucket,
)

EXAMPLE_CONFIG = ROOT / "examples" / "gcp_bootstrap" / "infra.py"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def cli():
    from python_tofu.cli.main import app

    return app


@pytest.fixture
def sample_stack() -> GcpStack:
    return GcpStack(
        provider=GcpProvider(project="demo-project", region="europe-west1"),
        backend=BackendConfig(kind="gcs", bucket="demo-project-state", prefix="demo"),
        projects=[GcpProject(project_id="demo-project", name="Demo Project")],
        apis=[ProjectApi(project="demo-project", service="storage.googleapis.com")],
        service_accounts=[
            ServiceAccount(
                project="demo-project",
                account_id="ci-runner",
                display_name="CI runner",
                roles=["roles/storage.admin"],
            )
        ],
        buckets=[
            StorageBucket(
                project="demo-project",
                name="demo-project-artifacts",
                location="EU",
                versioning=True,
            )
        ],
        iam_members=[
            ProjectIamMember(
                project="demo-project",
                role="roles/viewer",
                member="user:alice@example.com",
            )
        ],
    )


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "infra.py"
    path.write_text(
        """\
from python_tofu import (
    GcpProject,
    GcpProvider,
    GcpStack,
    ProjectApi,
    ServiceAccount,
    StorageBucket,
)

PROJECT_ID = "demo-project"

stack = GcpStack(
    provider=GcpProvider(project=PROJECT_ID, region="europe-west1"),
    projects=[GcpProject(project_id=PROJECT_ID, name="Demo Project")],
    apis=[ProjectApi(project=PROJECT_ID, service="storage.googleapis.com")],
    service_accounts=[
        ServiceAccount(
            project=PROJECT_ID,
            account_id="ci-runner",
            roles=["roles/storage.admin"],
        )
    ],
    buckets=[StorageBucket(project=PROJECT_ID, name="demo-project-artifacts")],
)
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def fake_tofu(tmp_path: Path) -> Path:
    """A stand-in ``tofu`` binary that never touches GCP."""

    binary = tmp_path / "fake-tofu"
    binary.write_text(
        """#!/bin/sh
case "$1" in
  show)
    echo '{"resource_changes":['
    echo '{"change":{"actions":["create"]}},'
    echo '{"change":{"actions":["update"]}}]}'
    ;;
  plan)
    echo "Plan: 1 to add, 1 to change, 0 to destroy."
    ;;
  output)
    echo '{"bucket": {"value": "demo-project-artifacts"}}'
    ;;
  *)
    echo "fake-tofu $*"
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary
