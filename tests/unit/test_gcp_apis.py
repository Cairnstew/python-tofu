from __future__ import annotations

import pytest

from python_tofu.providers.gcp import (
    BillingBudget,
    CloudRunService,
    GcpProvider,
    GcpStack,
    ProjectApi,
    PubSubSubscription,
    PubSubTopic,
    ServiceAccount,
    StorageBucket,
)
from python_tofu.providers.gcp import prune as gcp_prune
from python_tofu.providers.gcp.apis import (
    ARTIFACT_REGISTRY,
    CLOUD_BILLING,
    CLOUD_RESOURCE_MANAGER,
    IAM,
    PUBSUB,
    RUN,
    SERVICE_USAGE,
    STORAGE,
    declared_apis,
    required_apis,
)
from python_tofu.providers.gcp.renderer import GcpRenderer

PROJECT = "demo-project"


def _stack(**overrides: object) -> GcpStack:
    values: dict[str, object] = {
        "provider": GcpProvider(project=PROJECT, region="us-central1"),
    }
    values.update(overrides)
    return GcpStack(**values)  # type: ignore[arg-type]


def _main(stack: GcpStack) -> str:
    return " ".join(GcpRenderer(".tofu").render_text(stack)["main.tf"].split())


def _service(**overrides: object) -> CloudRunService:
    values: dict[str, object] = {
        "project": PROJECT,
        "name": "api",
        "image": "us-docker.pkg.dev/cloudrun/container/hello",
    }
    values.update(overrides)
    return CloudRunService(**values)  # type: ignore[arg-type]


def _account() -> ServiceAccount:
    return ServiceAccount(project=PROJECT, account_id="pusher")


def test_empty_stack_needs_no_apis() -> None:
    assert required_apis(_stack()) == {}
    assert declared_apis(_stack()) == ()


def test_required_apis_follow_resource_kinds() -> None:
    stack = _stack(
        service_accounts=[_account()],
        buckets=[StorageBucket(project=PROJECT, name="assets")],
        cloud_run_services=[_service(invoker_service_accounts=["pusher"])],
        pubsub_topics=[PubSubTopic(project=PROJECT, name="jobs")],
        pubsub_subscriptions=[
            PubSubSubscription(
                project=PROJECT,
                name="jobs-push",
                topic="jobs",
                push_service="api",
                push_service_account="pusher",
            )
        ],
    )

    assert required_apis(stack) == {
        PROJECT: tuple(sorted([SERVICE_USAGE, STORAGE, IAM, RUN, PUBSUB]))
    }


def test_billing_budget_needs_cloud_billing() -> None:
    budget = BillingBudget(
        billing_account="01ABCD-EFGH23-456789",
        display_name="guardrail",
        amount=5,
    )
    stack = _stack(billing_budgets=[budget])

    assert required_apis(stack) == {PROJECT: tuple(sorted([CLOUD_BILLING, SERVICE_USAGE]))}

    text = _main(stack)
    assert 'resource "google_project_service" "api_cloudbilling_googleapis_com"' in text
    assert "depends_on = [google_project_service.api_cloudbilling_googleapis_com]" in text


def test_subscription_without_push_does_not_need_run() -> None:
    stack = _stack(
        pubsub_topics=[PubSubTopic(project=PROJECT, name="jobs")],
        pubsub_subscriptions=[PubSubSubscription(project=PROJECT, name="jobs-pull", topic="jobs")],
    )

    assert RUN not in required_apis(stack)[PROJECT]
    assert PUBSUB in required_apis(stack)[PROJECT]


def test_declared_apis_adds_missing_services() -> None:
    stack = _stack(cloud_run_services=[_service()])

    services = {api.service for api in declared_apis(stack)}
    assert services == {RUN, SERVICE_USAGE}


def test_explicit_apis_are_kept_and_deduplicated() -> None:
    stack = _stack(
        apis=[ProjectApi(project=PROJECT, service=RUN)],
        cloud_run_services=[_service()],
    )

    apis = declared_apis(stack)
    assert [api.service for api in apis].count(RUN) == 1
    assert SERVICE_USAGE in {api.service for api in apis}


def test_auto_enable_can_be_disabled() -> None:
    stack = _stack(
        provider=GcpProvider(project=PROJECT, auto_enable_apis=False),
        apis=[ProjectApi(project=PROJECT, service=RUN)],
        cloud_run_services=[_service()],
    )

    assert [api.service for api in declared_apis(stack)] == [RUN]
    text = _main(stack)
    assert text.count('resource "google_project_service"') == 1


def test_external_projects_are_not_touched() -> None:
    stack = _stack(
        external_projects=["shared-project"],
        apis=[ProjectApi(project="shared-project", service=STORAGE)],
        buckets=[StorageBucket(project="shared-project", name="shared")],
    )

    assert "shared-project" not in required_apis(stack)
    # The explicit API declaration is still rendered.
    assert [api.project for api in declared_apis(stack)] == ["shared-project"]


def test_resources_depend_on_the_apis_they_need() -> None:
    stack = _stack(cloud_run_services=[_service()])
    text = _main(stack)

    assert 'resource "google_project_service" "api_run_googleapis_com"' in text
    assert "depends_on = [google_project_service.api_run_googleapis_com]" in text
    # The API resources themselves must not depend on anything.
    api_block = text.split('resource "google_project_service"')[1]
    assert "depends_on" not in api_block.split("}", 1)[0]


def test_invoker_bindings_depend_on_run_and_iam() -> None:
    stack = _stack(
        service_accounts=[_account()],
        cloud_run_services=[_service(invoker_service_accounts=["pusher"])],
    )
    text = _main(stack)

    assert "api_iam_googleapis_com" in text
    assert (
        "depends_on = [google_project_service.api_run_googleapis_com, "
        "google_project_service.api_iam_googleapis_com]" in text
    )


def test_service_account_roles_need_resource_manager() -> None:
    account = ServiceAccount(project=PROJECT, account_id="pusher", roles=["roles/run.admin"])
    stack = _stack(service_accounts=[account])

    assert CLOUD_RESOURCE_MANAGER in required_apis(stack)[PROJECT]


def test_functions_pull_in_build_and_eventarc() -> None:
    stack = _stack(
        buckets=[StorageBucket(project=PROJECT, name="src")],
        cloud_run_functions=[],
    )
    assert required_apis(stack)[PROJECT] == tuple(sorted([STORAGE, SERVICE_USAGE]))


def test_prune_treats_auto_apis_as_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gcp_prune, "access_token", lambda stack: "token")
    monkeypatch.setattr(gcp_prune, "list_buckets", lambda project, token: [])
    monkeypatch.setattr(gcp_prune, "list_service_accounts", lambda project, token: [])
    monkeypatch.setattr(gcp_prune, "list_topics", lambda project, token: [])
    monkeypatch.setattr(gcp_prune, "list_subscriptions", lambda project, token: [])
    monkeypatch.setattr(
        gcp_prune,
        "list_services",
        lambda project, token: [
            {"name": "projects/1/services/run.googleapis.com", "state": "ENABLED"},
            {"name": "projects/1/services/serviceusage.googleapis.com", "state": "ENABLED"},
            {"name": "projects/1/services/bigquery.googleapis.com", "state": "ENABLED"},
        ],
    )

    stack = _stack(cloud_run_services=[_service()])
    plan = gcp_prune.discover(stack, ("apis",))

    services = {resource.description for resource in plan.resources}
    assert services == {"API bigquery.googleapis.com"}


def test_artifact_repository_needs_artifact_registry() -> None:
    from python_tofu.providers.gcp import ArtifactRegistryRepository

    stack = _stack(
        artifact_registry_repositories=[
            ArtifactRegistryRepository(project=PROJECT, repository_id="apps")
        ]
    )

    assert required_apis(stack)[PROJECT] == tuple(sorted([ARTIFACT_REGISTRY, SERVICE_USAGE]))


def test_cloud_resource_manager_only_for_declared_projects() -> None:
    from python_tofu.providers.gcp import GcpProject

    stack = _stack(projects=[GcpProject(project_id="demo-project-two", name="Two")])

    assert CLOUD_RESOURCE_MANAGER in required_apis(stack)["demo-project-two"]
