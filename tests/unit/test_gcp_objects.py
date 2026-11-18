from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from python_tofu.models import (
    BucketObject,
    GcpProvider,
    GcpStack,
    ProjectIamMember,
    ServiceAccount,
    ServiceAccountIamMember,
    StorageBucket,
)
from python_tofu.services.renderer import Renderer


def _stack(*objects: BucketObject) -> GcpStack:
    return GcpStack(
        provider=GcpProvider(project="demo-project"),
        buckets=[
            StorageBucket(project="demo-project", name="demo-project-artifacts"),
        ],
        bucket_objects=list(objects),
    )


def test_object_requires_exactly_one_content_source() -> None:
    for kwargs in (
        {},
        {"content": "x", "source": "file.txt"},
        {"source": "file.txt", "source_url": "https://example.com/x"},
    ):
        with pytest.raises(ValidationError, match="exactly one of content, source or source_url"):
            BucketObject(bucket="demo-project-artifacts", name="x", **kwargs)


@pytest.mark.parametrize("name", ["", "/absolute", "line\nbreak"])
def test_object_name_is_validated(name: str) -> None:
    with pytest.raises(ValidationError):
        BucketObject(bucket="demo-project-artifacts", name=name, content="x")


def test_object_url_must_be_http() -> None:
    with pytest.raises(ValidationError, match="http"):
        BucketObject(
            bucket="demo-project-artifacts",
            name="x",
            source_url="gs://other-bucket/x",
        )


def test_stack_rejects_unknown_bucket_references() -> None:
    with pytest.raises(ValidationError, match="unknown buckets"):
        GcpStack(
            provider=GcpProvider(project="demo-project"),
            bucket_objects=[
                BucketObject(bucket="not-declared", name="x", content="x"),
            ],
        )


def test_external_buckets_are_allowed() -> None:
    stack = GcpStack(
        provider=GcpProvider(project="demo-project"),
        external_buckets=["shared-cache"],
        bucket_objects=[BucketObject(bucket="shared-cache", name="x", content="x")],
    )
    assert stack.bucket_objects[0].bucket == "shared-cache"


def test_bucket_name_rejects_an_hcl_interpolation() -> None:
    with pytest.raises(ValidationError, match="must be a literal"):
        StorageBucket(project="demo-project", name="${google_project.p.project_id}-assets")


def test_iam_member_accepts_a_principal_interpolation() -> None:
    stack = GcpStack(
        provider=GcpProvider(project="demo-project"),
        iam_members=[
            ProjectIamMember(
                project="demo-project",
                role="roles/storage.admin",
                member="serviceAccount:${google_service_account.sa_ci.email}",
            )
        ],
    )
    main = Renderer(".tofu").render_text(stack)["main.tf"]
    assert '"serviceAccount:${google_service_account.sa_ci.email}"' in main


def test_object_accepts_a_bucket_interpolation() -> None:
    stack = _stack(
        BucketObject(
            bucket="${google_storage_bucket.bucket_other.name}",
            name="x.txt",
            content="x",
        )
    )
    main = Renderer(".tofu").render_text(stack)["main.tf"]
    assert '"${google_storage_bucket.bucket_other.name}"' in main
    assert "google_storage_bucket.bucket_demo_project_artifacts.name" not in main


def test_iam_member_accepts_a_declared_service_account() -> None:
    stack = GcpStack(
        provider=GcpProvider(project="demo-project"),
        service_accounts=[ServiceAccount(project="demo-project", account_id="ci-runner")],
        iam_members=[
            ProjectIamMember(
                project="demo-project",
                role="roles/storage.admin",
                service_account="ci-runner",
            )
        ],
    )
    main = Renderer(".tofu").render_text(stack)["main.tf"]
    assert 'member     = "serviceAccount:${google_service_account.sa_ci_runner.email}"' in main


def test_iam_member_requires_exactly_one_principal() -> None:
    for kwargs in (
        {},
        {
            "member": "user:alice@example.com",
            "service_account": "ci-runner",
        },
    ):
        with pytest.raises(ValidationError, match="exactly one of member or service_account"):
            ProjectIamMember(project="demo-project", role="roles/viewer", **kwargs)


def test_service_account_iam_member_renders_delegation() -> None:
    stack = GcpStack(
        provider=GcpProvider(project="demo-project"),
        service_accounts=[ServiceAccount(project="demo-project", account_id="ci-runner")],
        service_account_iam_members=[
            ServiceAccountIamMember(
                service_account="ci-runner",
                role="roles/iam.serviceAccountTokenCreator",
                member="user:alice@example.com",
            ),
            ServiceAccountIamMember(
                service_account="ci-runner@demo-project.iam.gserviceaccount.com",
                role="roles/iam.serviceAccountUser",
                member="ci-runner",
            ),
        ],
    )
    main = Renderer(".tofu").render_text(stack)["main.tf"]
    assert "service_account_id = google_service_account.sa_ci_runner.name" in main
    assert 'role               = "roles/iam.serviceAccountTokenCreator"' in main
    assert 'member             = "user:alice@example.com"' in main
    delegated = 'member             = "serviceAccount:${google_service_account.sa_ci_runner.email}"'
    assert delegated in main


def test_unknown_service_account_reference_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown service accounts"):
        GcpStack(
            provider=GcpProvider(project="demo-project"),
            service_account_iam_members=[
                ServiceAccountIamMember(
                    service_account="missing-account",
                    role="roles/iam.serviceAccountUser",
                    member="user:alice@example.com",
                )
            ],
        )


def test_duplicate_objects_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate bucket object"):
        _stack(
            BucketObject(bucket="demo-project-artifacts", name="same", content="a"),
            BucketObject(bucket="demo-project-artifacts", name="same", content="b"),
        )


def test_inline_text_renders_content_and_guessed_type() -> None:
    main = Renderer(".tofu").render_text(
        _stack(
            BucketObject(
                bucket="demo-project-artifacts",
                name="config/app.json",
                content='{"release": "v1"}',
                metadata={"env": "prod"},
            )
        )
    )["main.tf"]

    assert 'resource "google_storage_bucket_object" "object_config_app_json"' in main
    assert "google_storage_bucket.bucket_demo_project_artifacts.name" in main
    assert '"config/app.json"' in main
    assert '"application/json"' in main
    assert '"env" = "prod"' in main
    assert '\\"release\\": \\"v1\\"' in main


def test_explicit_content_type_wins() -> None:
    main = Renderer(".tofu").render_text(
        _stack(
            BucketObject(
                bucket="demo-project-artifacts",
                name="config/app.json",
                content="{}",
                content_type="application/vnd.acme+json",
                cache_control="no-store",
            )
        )
    )["main.tf"]
    assert '"application/vnd.acme+json"' in main
    assert '"no-store"' in main


def test_local_source_is_rendered_as_an_absolute_path(tmp_path: Path) -> None:
    payload = tmp_path / "payload.txt"
    payload.write_text("hello", encoding="utf-8")

    main = Renderer(".tofu").render_text(
        _stack(
            BucketObject(
                bucket="demo-project-artifacts",
                name="payload.txt",
                source=str(payload),
            )
        )
    )["main.tf"]

    assert f'"{payload.resolve()}"' in main
    assert '"text/plain"' in main


def test_url_source_emits_http_data_block_and_provider() -> None:
    files = Renderer(".tofu").render_text(
        _stack(
            BucketObject(
                bucket="demo-project-artifacts",
                name="remote/config.json",
                source_url="https://example.com/config.json",
            )
        )
    )

    assert 'data "http" "object_remote_config_json"' in files["main.tf"]
    assert 'url = "https://example.com/config.json"' in files["main.tf"]
    assert "data.http.object_remote_config_json.response_body" in files["main.tf"]
    assert '"source" = "hashicorp/http"' in files["versions.tf"]


def test_http_provider_is_omitted_without_url_objects() -> None:
    versions = Renderer(".tofu").render_text(_stack())["versions.tf"]
    assert "hashicorp/http" not in versions


def test_bytes_are_materialised_and_referenced_by_source(tmp_path: Path) -> None:
    workdir = tmp_path / "tofu"
    stack = _stack(
        BucketObject(
            bucket="demo-project-artifacts",
            name="blob.bin",
            content=b"\x00\x01\x02raw",
        )
    )

    Renderer(workdir).render(stack)

    main = (workdir / "main.tf").read_text()
    source_line = next(line for line in main.splitlines() if line.strip().startswith("source"))
    referenced = Path(source_line.split('"')[1])
    assert referenced.parent == workdir / ".objects"
    assert referenced.read_bytes() == b"\x00\x01\x02raw"
    assert ".objects/" in (workdir / ".gitignore").read_text()


def test_external_bucket_is_rendered_as_a_literal() -> None:
    stack = GcpStack(
        provider=GcpProvider(project="demo-project"),
        external_buckets=["shared-cache"],
        bucket_objects=[BucketObject(bucket="shared-cache", name="x.txt", content="x")],
    )
    main = Renderer(".tofu").render_text(stack)["main.tf"]
    assert '"shared-cache"' in main
    assert "google_storage_bucket.bucket_shared_cache" not in main


def test_object_output_is_deterministic() -> None:
    stack = _stack(BucketObject(bucket="demo-project-artifacts", name="x.txt", content="same"))
    renderer = Renderer(".tofu")
    assert renderer.render_text(stack) == renderer.render_text(stack)
