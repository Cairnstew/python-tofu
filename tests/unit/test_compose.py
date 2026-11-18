from __future__ import annotations

import pytest

from python_tofu import Output, ref
from python_tofu.providers.gcp import (
    GcpProvider,
    GcpStack,
    ProjectApi,
    ProjectIamMember,
    ServiceAccount,
    StackPart,
    StorageBucket,
    compose,
)
from python_tofu.providers.gcp.parts import part_sections
from python_tofu.providers.gcp.renderer import GcpRenderer

PROJECT = "demo-project"


def _bucket(name: str) -> StorageBucket:
    return StorageBucket(project=PROJECT, name=name)


def _account(account_id: str) -> ServiceAccount:
    return ServiceAccount(project=PROJECT, account_id=account_id)


def test_compose_merges_parts_into_stack_arguments() -> None:
    foundation = StackPart(
        name="foundation",
        apis=[ProjectApi(project=PROJECT, service="storage.googleapis.com")],
    )
    storage = StackPart(
        name="storage",
        buckets=[_bucket("demo-artifacts")],
        external_buckets=["pre-existing"],
    )
    iam = StackPart(name="iam", service_accounts=[_account("ci-runner")])

    merged = compose(foundation, storage, iam)
    stack = GcpStack(provider=GcpProvider(project=PROJECT), **merged)

    assert [item.name for item in stack.buckets] == ["demo-artifacts"]
    assert [item.account_id for item in stack.service_accounts] == ["ci-runner"]
    assert stack.external_buckets == ["pre-existing"]


def test_compose_preserves_part_order_within_a_section() -> None:
    first = StackPart(name="first", buckets=[_bucket("a-bucket")])
    second = StackPart(name="second", buckets=[_bucket("b-bucket")])

    merged = compose(first, second)

    assert [item.name for item in merged["buckets"]] == ["a-bucket", "b-bucket"]


def test_compose_merges_outputs_and_rejects_duplicates() -> None:
    one = StackPart(name="one", outputs=[Output("url", ref("google_storage_bucket.a.name"))])
    two = StackPart(name="two", outputs=[Output("url", "literal")])

    with pytest.raises(ValueError, match=r"duplicate output 'url': .*'one'.*'two'"):
        compose(one, two)


def test_compose_names_both_parts_in_a_duplicate_error() -> None:
    foundation = StackPart(name="foundation", buckets=[_bucket("demo-artifacts")])
    storage = StackPart(name="storage", buckets=[_bucket("demo-artifacts")])

    with pytest.raises(ValueError, match=r"bucket 'demo-artifacts': .*'foundation'.*'storage'"):
        compose(foundation, storage)


def test_compose_rejects_duplicate_part_names() -> None:
    with pytest.raises(ValueError, match="duplicate StackPart name 'same'"):
        compose(StackPart(name="same"), StackPart(name="same"))


def test_compose_deduplicates_external_references() -> None:
    one = StackPart(name="one", external_projects=["shared-project"], external_topics=["jobs"])
    two = StackPart(name="two", external_projects=["shared-project"], external_topics=["jobs"])

    merged = compose(one, two)

    assert merged["external_projects"] == ["shared-project"]
    assert merged["external_topics"] == ["jobs"]


def test_compose_with_no_parts_returns_no_arguments() -> None:
    assert compose() == {}


def test_part_name_must_not_be_blank() -> None:
    with pytest.raises(ValueError, match="non-empty name"):
        StackPart(name="  ")


def test_compose_distinguishes_service_account_bindings() -> None:
    parts = [
        StackPart(
            name="one",
            iam_members=[
                ProjectIamMember(
                    project=PROJECT,
                    role="roles/viewer",
                    service_account="one@demo-project.iam.gserviceaccount.com",
                )
            ],
        ),
        StackPart(
            name="two",
            iam_members=[
                ProjectIamMember(
                    project=PROJECT,
                    role="roles/viewer",
                    service_account="two@demo-project.iam.gserviceaccount.com",
                )
            ],
        ),
    ]

    stack = GcpStack(provider=GcpProvider(project=PROJECT), **compose(*parts))
    assert len(stack.iam_members) == 2


def test_every_part_section_exists_on_the_stack() -> None:
    stack_fields = set(GcpStack.model_fields)
    sections = set(part_sections())

    assert sections <= stack_fields
    assert sections >= {"buckets", "pubsub_topics", "cloud_run_services", "outputs"}


def test_composed_stack_renders_the_same_resources() -> None:
    parts = [
        StackPart(
            name="foundation",
            apis=[ProjectApi(project=PROJECT, service="storage.googleapis.com")],
        ),
        StackPart(name="storage", buckets=[_bucket("demo-artifacts")]),
    ]

    assembled = GcpStack(provider=GcpProvider(project=PROJECT), **compose(*parts))
    direct = GcpStack(
        provider=GcpProvider(project=PROJECT),
        apis=[ProjectApi(project=PROJECT, service="storage.googleapis.com")],
        buckets=[_bucket("demo-artifacts")],
    )

    assert (
        GcpRenderer(".tofu").render_text(assembled)["main.tf"]
        == (GcpRenderer(".tofu").render_text(direct)["main.tf"])
    )
