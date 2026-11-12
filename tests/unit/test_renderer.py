from __future__ import annotations

from pathlib import Path

import pytest

from python_tofu.exceptions import RenderError
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
from python_tofu.services.renderer import Renderer, slug


def test_slug_sanitises_identifiers() -> None:
    assert slug("demo-project") == "demo_project"
    assert slug("roles/storage.admin") == "roles_storage_admin"
    assert slug("123") == "r_123"
    assert slug("---") == "resource"


def test_render_text_contains_every_resource(sample_stack: GcpStack) -> None:
    files = Renderer(".tofu").render_text(sample_stack)

    assert set(files) == {"versions.tf", "providers.tf", "main.tf", ".gitignore"}

    versions = files["versions.tf"]
    assert 'required_version = ">= 1.6.0"' in versions
    assert '"source" = "hashicorp/google"' in versions
    assert 'backend "gcs"' in versions
    assert 'bucket = "demo-project-state"' in versions

    providers = files["providers.tf"]
    assert 'provider "google"' in providers
    assert '"demo-project"' in providers
    assert '"europe-west1"' in providers

    main = files["main.tf"]
    assert 'resource "google_project" "project_demo_project"' in main
    assert 'resource "google_project_service" "api_storage_googleapis_com"' in main
    assert 'resource "google_service_account" "sa_ci_runner"' in main
    assert "serviceAccount:${google_service_account.sa_ci_runner.email}" in main
    assert 'resource "google_storage_bucket" "bucket_demo_project_artifacts"' in main
    assert 'resource "google_project_iam_member" "iam_roles_viewer_user_alice_example_com"' in main
    assert "versioning {" in main
    assert "enabled = true" in main


def test_render_writes_managed_files(tmp_path: Path, sample_stack: GcpStack) -> None:
    workdir = tmp_path / "tofu"
    result = Renderer(workdir).render(sample_stack)

    # Six declared resources plus three auto-enabled APIs (service usage, IAM,
    # Cloud Resource Manager) that their resources need.
    assert result.resources == 9
    assert workdir.is_dir()
    assert {path.name for path in result.files} == {
        "versions.tf",
        "providers.tf",
        "main.tf",
        ".gitignore",
    }
    assert "*.tfstate" in (workdir / ".gitignore").read_text()


def test_extra_files_are_written(tmp_path: Path, sample_stack: GcpStack) -> None:
    stack = sample_stack.model_copy(
        update={"extra_files": {"biglake.tf": 'resource "google_biglake_catalog" "x" {}\n'}}
    )

    files = Renderer(tmp_path).render_text(stack)
    assert "biglake.tf" in files
    assert "google_biglake_catalog" in files["biglake.tf"]

    result = Renderer(tmp_path).render(stack)
    assert (tmp_path / "biglake.tf").read_text() == files["biglake.tf"]
    assert "biglake.tf" in {path.name for path in result.files}
    # Six declared resources plus three auto-enabled APIs (service usage, IAM,
    # Cloud Resource Manager) that their resources need.
    assert result.resources == 9


def test_extra_files_cannot_override_managed(tmp_path: Path, sample_stack: GcpStack) -> None:
    stack = sample_stack.model_copy(update={"extra_files": {"main.tf": "# nope\n"}})

    with pytest.raises(RenderError, match="managed file"):
        Renderer(tmp_path).render_text(stack)


def test_extra_files_require_flat_tf_names(tmp_path: Path, sample_stack: GcpStack) -> None:
    for name in ("nested/extra.tf", "extra.hcl", ""):
        stack = sample_stack.model_copy(update={"extra_files": {name: "# nope\n"}})
        with pytest.raises(RenderError):
            Renderer(tmp_path).render_text(stack)


def test_render_is_deterministic(sample_stack: GcpStack) -> None:
    renderer = Renderer(".tofu")
    assert renderer.render_text(sample_stack) == renderer.render_text(sample_stack)


def test_duplicate_bucket_names_raise(sample_stack: GcpStack) -> None:
    duplicated = sample_stack.model_copy(
        update={
            "buckets": [
                *sample_stack.buckets,
                StorageBucket(project="demo-project", name="demo-project-artifacts"),
            ]
        }
    )
    with pytest.raises(RenderError, match="duplicate resource address"):
        Renderer(".tofu").render_text(duplicated)


def test_duplicate_iam_bindings_raise(sample_stack: GcpStack) -> None:
    binding = ProjectIamMember(
        project="demo-project", role="roles/viewer", member="user:alice@example.com"
    )
    duplicated = sample_stack.model_copy(
        update={"iam_members": [*sample_stack.iam_members, binding]}
    )
    with pytest.raises(RenderError, match="duplicate resource address"):
        Renderer(".tofu").render_text(duplicated)


def test_empty_stack_renders_comment() -> None:
    stack = GcpStack(provider=GcpProvider(project="demo-project"))
    files = Renderer(".tofu").render_text(stack)
    assert files["main.tf"] == "# No resources declared in the stack.\n"
    assert "backend" not in files["versions.tf"]


def test_local_backend(tmp_path: Path) -> None:
    stack = GcpStack(
        provider=GcpProvider(project="demo-project"),
        backend=BackendConfig(kind="local", path="terraform.tfstate"),
    )
    versions = Renderer(tmp_path).render_text(stack)["versions.tf"]
    assert 'backend "local"' in versions
    assert 'path = "terraform.tfstate"' in versions


def test_service_account_roles_are_sorted() -> None:
    stack = GcpStack(
        provider=GcpProvider(project="demo-project"),
        projects=[GcpProject(project_id="demo-project", name="Demo")],
        service_accounts=[
            ServiceAccount(
                project="demo-project",
                account_id="ci-runner",
                roles=["roles/viewer", "roles/editor"],
            )
        ],
    )
    main = Renderer(".tofu").render_text(stack)["main.tf"]
    assert main.index("roles/editor") < main.index("roles/viewer")


def test_project_api_and_bucket_optional_fields_are_omitted() -> None:
    stack = GcpStack(
        provider=GcpProvider(project="demo-project"),
        projects=[GcpProject(project_id="demo-project", name="Demo")],
        apis=[ProjectApi(project="demo-project", service="storage.googleapis.com")],
        buckets=[StorageBucket(project="demo-project", name="demo-project-artifacts")],
    )
    main = Renderer(".tofu").render_text(stack)["main.tf"]
    assert "billing_account" not in main
    assert "org_id" not in main
    assert "labels" not in main
