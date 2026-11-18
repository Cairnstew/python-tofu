from __future__ import annotations

import pytest

from python_tofu.providers.gcp import (
    BillingBudget,
    CloudRunFunction,
    CloudRunJob,
    CloudRunService,
    CloudRunWorkerPool,
    CloudSqlVolume,
    DeadLetter,
    GcpProject,
    GcpProvider,
    GcpStack,
    GcsVolume,
    ProjectApi,
    PubSubSubscription,
    PubSubTopic,
    SecretEnv,
    SecretVolume,
    ServiceAccount,
    ServiceAccountIamMember,
    StorageBucket,
    Volume,
)
from python_tofu.providers.gcp import prune as gcp_prune
from python_tofu.providers.gcp.apis import (
    ARTIFACT_REGISTRY,
    BILLING_BUDGETS,
    CLOUD_BILLING,
    CLOUD_RESOURCE_MANAGER,
    CLOUD_SQL,
    DEFAULT_APIS,
    IAM,
    IAM_CREDENTIALS,
    LOGGING,
    PUBSUB,
    RUN,
    SECRET_MANAGER,
    SERVICE_USAGE,
    STORAGE,
    declared_apis,
    required_apis,
)
from python_tofu.providers.gcp.renderer import GcpRenderer

PROJECT = "demo-project"


def _expected(*services: str) -> tuple[str, ...]:
    return tuple(sorted({*DEFAULT_APIS, *services}))


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
        PROJECT: _expected(STORAGE, IAM, RUN, PUBSUB, CLOUD_RESOURCE_MANAGER)
    }


def test_billing_budget_needs_billing_budgets() -> None:
    budget = BillingBudget(
        billing_account="01ABCD-EFGH23-456789",
        display_name="guardrail",
        amount=5,
    )
    stack = _stack(billing_budgets=[budget])

    assert required_apis(stack) == {PROJECT: _expected(BILLING_BUDGETS)}

    text = _main(stack)
    assert 'resource "google_project_service" "api_billingbudgets_googleapis_com"' in text
    assert "depends_on = [google_project_service.api_billingbudgets_googleapis_com]" in text
    assert BILLING_BUDGETS in required_apis(stack)[PROJECT]


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
    assert services == {*DEFAULT_APIS, RUN}


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
    stack = _stack(
        provider=GcpProvider(project=PROJECT, default_apis=()),
        service_accounts=[account],
    )

    assert CLOUD_RESOURCE_MANAGER in required_apis(stack)[PROJECT]


def test_service_account_iam_binding_needs_only_iam() -> None:
    stack = _stack(
        provider=GcpProvider(project=PROJECT, default_apis=()),
        service_accounts=[ServiceAccount(project=PROJECT, account_id="pusher")],
        service_account_iam_members=[
            ServiceAccountIamMember(
                service_account="pusher",
                role="roles/iam.serviceAccountTokenCreator",
                member="user:alice@example.com",
            )
        ],
    )

    services = required_apis(stack)[PROJECT]
    assert IAM in services
    assert CLOUD_RESOURCE_MANAGER not in services


def test_functions_pull_in_build_and_eventarc() -> None:
    stack = _stack(
        buckets=[StorageBucket(project=PROJECT, name="src")],
        cloud_run_functions=[],
    )
    assert required_apis(stack)[PROJECT] == _expected(STORAGE)


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

    assert required_apis(stack)[PROJECT] == _expected(ARTIFACT_REGISTRY)


def test_cloud_resource_manager_only_for_declared_projects() -> None:
    from python_tofu.providers.gcp import GcpProject

    stack = _stack(
        provider=GcpProvider(project=PROJECT, default_apis=()),
        projects=[GcpProject(project_id="demo-project-two", name="Two")],
    )

    assert CLOUD_RESOURCE_MANAGER in required_apis(stack)["demo-project-two"]


def test_project_with_billing_account_needs_cloud_billing() -> None:
    stack = _stack(
        provider=GcpProvider(project=PROJECT, default_apis=()),
        projects=[
            GcpProject(
                project_id="demo-project-two",
                name="Two",
                billing_account="01ABCD-EFGH23-456789",
            )
        ],
    )

    assert CLOUD_BILLING in required_apis(stack)["demo-project-two"]


def test_provider_impersonation_needs_iam_credentials() -> None:
    stack = _stack(
        provider=GcpProvider(
            project=PROJECT,
            default_apis=(),
            impersonate_service_account=f"tofu@{PROJECT}.iam.gserviceaccount.com",
        )
    )

    assert IAM_CREDENTIALS in required_apis(stack)[PROJECT]


def test_service_secret_env_needs_secret_manager() -> None:
    stack = _stack(
        cloud_run_services=[_service(secret_env={"API_KEY": SecretEnv(secret="api-key")})]
    )

    assert SECRET_MANAGER in required_apis(stack)[PROJECT]


def test_service_volumes_need_their_apis() -> None:
    stack = _stack(
        cloud_run_services=[
            _service(
                volumes=[
                    Volume(name="cache", mount_path="/mnt/cache", gcs=GcsVolume(bucket="assets")),
                    Volume(
                        name="sql",
                        mount_path="/cloudsql",
                        cloud_sql=CloudSqlVolume(instances=["demo-project:us-central1:db"]),
                    ),
                    Volume(
                        name="secrets",
                        mount_path="/secrets",
                        secret=SecretVolume(secret="api-key"),
                    ),
                ]
            )
        ]
    )

    services = required_apis(stack)[PROJECT]
    assert STORAGE in services
    assert CLOUD_SQL in services
    assert SECRET_MANAGER in services


def test_job_secret_env_needs_secret_manager() -> None:
    stack = _stack(
        cloud_run_jobs=[
            CloudRunJob(
                project=PROJECT,
                name="batch",
                image="us-docker.pkg.dev/demo-project/repo/batch:latest",
                secret_env={"API_KEY": SecretEnv(secret="api-key")},
            )
        ]
    )

    assert SECRET_MANAGER in required_apis(stack)[PROJECT]


def test_worker_pool_secret_env_needs_secret_manager() -> None:
    stack = _stack(
        cloud_run_worker_pools=[
            CloudRunWorkerPool(
                project=PROJECT,
                name="worker",
                image="us-docker.pkg.dev/demo-project/repo/worker:latest",
                secret_env={"API_KEY": SecretEnv(secret="api-key")},
            )
        ]
    )

    assert SECRET_MANAGER in required_apis(stack)[PROJECT]


def test_function_needs_pubsub_logging_and_secret_manager() -> None:
    stack = _stack(
        buckets=[StorageBucket(project=PROJECT, name="src")],
        cloud_run_functions=[
            CloudRunFunction(
                project=PROJECT,
                name="hello",
                runtime="python312",
                entry_point="hello_http",
                source_bucket="src",
                source_object="hello.zip",
                secret_env={"API_KEY": SecretEnv(secret="api-key")},
            )
        ],
    )

    services = required_apis(stack)[PROJECT]
    assert PUBSUB in services
    assert LOGGING in services
    assert SECRET_MANAGER in services


def test_subscription_dead_letter_needs_resource_manager() -> None:
    stack = _stack(
        provider=GcpProvider(project=PROJECT, default_apis=()),
        pubsub_topics=[
            PubSubTopic(project=PROJECT, name="jobs"),
            PubSubTopic(project=PROJECT, name="jobs-dlq"),
        ],
        pubsub_subscriptions=[
            PubSubSubscription(
                project=PROJECT,
                name="jobs-pull",
                topic="jobs",
                dead_letter=DeadLetter(topic="jobs-dlq"),
            )
        ],
    )

    services = required_apis(stack)[PROJECT]
    assert IAM in services
    assert CLOUD_RESOURCE_MANAGER in services


def test_subscription_push_oidc_needs_resource_manager() -> None:
    stack = _stack(
        provider=GcpProvider(project=PROJECT, default_apis=()),
        pubsub_topics=[PubSubTopic(project=PROJECT, name="jobs")],
        pubsub_subscriptions=[
            PubSubSubscription(
                project=PROJECT,
                name="jobs-push",
                topic="jobs",
                push_endpoint="https://example.com/hook",
                push_service_account="pusher@demo-project.iam.gserviceaccount.com",
            )
        ],
    )

    services = required_apis(stack)[PROJECT]
    assert IAM in services
    assert CLOUD_RESOURCE_MANAGER in services
