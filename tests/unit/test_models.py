from __future__ import annotations

import pytest
from pydantic import ValidationError

from python_tofu.models import (
    BackendConfig,
    GcpProject,
    GcpProvider,
    GcpStack,
    ProjectApi,
    ProjectIamMember,
    ServiceAccount,
    StorageBucket,
)


def test_valid_project() -> None:
    project = GcpProject(project_id="demo-project", name="Demo")
    assert project.project_id == "demo-project"


@pytest.mark.parametrize("value", ["Demo", "demo", "-demo-project", "demo-project-", "a b c"])
def test_invalid_project_id(value: str) -> None:
    with pytest.raises(ValidationError):
        GcpProject(project_id=value, name="Demo")


def test_project_cannot_have_org_and_folder() -> None:
    with pytest.raises(ValidationError):
        GcpProject(project_id="demo-project", name="Demo", org_id="1", folder_id="2")


@pytest.mark.parametrize("value", ["ab", "Demo-Bucket", "bucket.", "-bucket"])
def test_invalid_bucket_name(value: str) -> None:
    with pytest.raises(ValidationError):
        StorageBucket(project="demo-project", name=value)


def test_service_account_id_and_roles_are_validated() -> None:
    with pytest.raises(ValidationError):
        ServiceAccount(project="demo-project", account_id="bad_id")
    with pytest.raises(ValidationError):
        ServiceAccount(
            project="demo-project",
            account_id="ci-runner",
            roles=["storage.admin"],
        )


def test_stack_rejects_unknown_project_references() -> None:
    with pytest.raises(ValidationError, match="unknown projects"):
        GcpStack(
            provider=GcpProvider(project="demo-project"),
            apis=[ProjectApi(project="other-project", service="storage.googleapis.com")],
        )


def test_external_projects_are_allowed() -> None:
    stack = GcpStack(
        provider=GcpProvider(project="demo-project"),
        external_projects=["existing-project"],
        buckets=[StorageBucket(project="existing-project", name="existing-artifacts")],
    )
    assert stack.buckets[0].project == "existing-project"


def test_gcs_backend_requires_bucket() -> None:
    with pytest.raises(ValidationError):
        BackendConfig(kind="gcs", bucket=None)


def test_local_backend_requires_path() -> None:
    with pytest.raises(ValidationError):
        BackendConfig(kind="local", path=None)


def test_iam_member_role_is_validated() -> None:
    with pytest.raises(ValidationError):
        ProjectIamMember(
            project="demo-project",
            role="storage.admin",
            member="user:alice@example.com",
        )


def test_models_are_immutable() -> None:
    project = GcpProject(project_id="demo-project", name="Demo")
    with pytest.raises(ValidationError):
        project.name = "Other"


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        GcpProject(project_id="demo-project", name="Demo", typo=True)
