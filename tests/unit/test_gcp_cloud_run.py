from __future__ import annotations

import pytest
from pydantic import ValidationError

from python_tofu.core.exceptions import RenderError
from python_tofu.providers.gcp import (
    ArtifactRegistryRepository,
    BucketObject,
    CloudRunFunction,
    CloudRunJob,
    CloudRunService,
    CloudRunWorkerPool,
    CloudSqlVolume,
    EmptyDirVolume,
    GcpProvider,
    GcpStack,
    GcsVolume,
    HttpProbe,
    NfsVolume,
    Probe,
    SecretEnv,
    SecretVolume,
    ServiceAccount,
    StorageBucket,
    TcpProbe,
    Volume,
)
from python_tofu.providers.gcp.renderer import GcpRenderer

PROJECT = "demo-project"


def _service(**overrides: object) -> CloudRunService:
    values: dict[str, object] = {
        "project": PROJECT,
        "name": "hello",
        "image": "us-docker.pkg.dev/cloudrun/container/hello",
    }
    values.update(overrides)
    return CloudRunService(**values)  # type: ignore[arg-type]


def _function(**overrides: object) -> CloudRunFunction:
    values: dict[str, object] = {
        "project": PROJECT,
        "name": "hello-fn",
        "runtime": "python312",
        "entry_point": "hello_http",
        "source_bucket": "demo-source",
        "source_object": "hello.zip",
    }
    values.update(overrides)
    return CloudRunFunction(**values)  # type: ignore[arg-type]


def _stack(**overrides: object) -> GcpStack:
    values: dict[str, object] = {
        "provider": GcpProvider(project=PROJECT, region="us-central1"),
        "buckets": [
            StorageBucket(project=PROJECT, name="demo-source", location="US"),
        ],
        "bucket_objects": [
            BucketObject(bucket="demo-source", name="hello.zip", content="zip"),
        ],
    }
    values.update(overrides)
    return GcpStack(**values)  # type: ignore[arg-type]


def _main(stack: GcpStack) -> str:
    return GcpRenderer(".tofu").render_text(stack)["main.tf"]


# ── hardened defaults ─────────────────────────────────────────────────
def test_service_defaults_are_private_and_capped() -> None:
    text = _main(_stack(cloud_run_services=[_service()]))

    assert 'resource "google_cloud_run_v2_service" "run_hello"' in text
    assert 'ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"' in text
    assert "deletion_protection = true" in text
    assert "min_instance_count = 0" in text
    assert "max_instance_count = 10" in text
    assert '"cpu"    = "1"' in text or '"cpu" = "1"' in text
    assert '"memory" = "512Mi"' in text or '"memory" = "512Mi"' in text
    assert "allUsers" not in text


def test_function_defaults_are_private_and_capped() -> None:
    text = _main(_stack(cloud_run_functions=[_function()]))

    assert 'resource "google_cloudfunctions2_function" "fn_hello_fn"' in text
    assert "ALLOW_INTERNAL_ONLY" in text
    assert "min_instance_count" in text and "= 0" in text
    assert "max_instance_count" in text and "= 10" in text
    assert '"256M"' in text
    assert "allUsers" not in text


# ── opt-in exposure and wiring ────────────────────────────────────────
def test_public_service_adds_invoker_binding() -> None:
    service = _service(allow_unauthenticated=True, ingress="all")
    text = _main(_stack(cloud_run_services=[service]))

    assert '"INGRESS_TRAFFIC_ALL"' in text
    assert 'resource "google_cloud_run_v2_service_iam_member" "run_invoker_hello"' in text
    assert '"roles/run.invoker"' in text
    assert '"allUsers"' in text


def test_public_function_adds_invoker_binding() -> None:
    function = _function(allow_unauthenticated=True, ingress="all")
    text = _main(_stack(cloud_run_functions=[function]))

    assert '"ALLOW_ALL"' in text
    assert (
        'resource "google_cloudfunctions2_function_iam_member" "function_invoker_hello_fn"' in text
    )
    assert 'role           = "roles/cloudfunctions.invoker"' in text


def test_service_account_reference_is_wired() -> None:
    account = ServiceAccount(project=PROJECT, account_id="hello-runtime")
    service = _service(service_account="hello-runtime")
    function = _function(service_account="hello-runtime")
    text = _main(
        _stack(
            service_accounts=[account], cloud_run_services=[service], cloud_run_functions=[function]
        )
    )

    assert "service_account = google_service_account.sa_hello_runtime.email" in text
    assert "service_account_email = google_service_account.sa_hello_runtime.email" in text


def test_function_source_references_declared_object() -> None:
    text = _main(_stack(cloud_run_functions=[_function()]))

    assert "bucket     = google_storage_bucket_object.object_hello_zip.bucket" in text
    assert "object     = google_storage_bucket_object.object_hello_zip.name" in text
    assert "generation = google_storage_bucket_object.object_hello_zip.generation" in text


def test_function_source_can_be_external_literals() -> None:
    stack = _stack(
        buckets=[],
        bucket_objects=[],
        external_buckets=["external-source"],
        cloud_run_functions=[_function(source_bucket="external-source")],
    )
    text = _main(stack)

    assert '"external-source"' in text
    assert '"hello.zip"' in text
    assert "generation" not in text


def test_env_and_secret_env_render() -> None:
    service = _service(
        env={"LOG_LEVEL": "info"},
        secret_env={"TOKEN": SecretEnv(secret="my-secret", version="7")},
    )
    text = _main(_stack(cloud_run_services=[service]))

    assert 'name  = "LOG_LEVEL"' in text
    assert 'value = "info"' in text
    assert "secret_key_ref" in text
    assert 'secret  = "my-secret"' in text
    assert 'version = "7"' in text


# ── validation ────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "Hello", "service names"),
        ("memory", "512MB", "memory"),
        ("timeout", "5m", "timeout"),
    ],
)
def test_service_rejects_invalid_fields(field: str, value: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _service(**{field: value})


def test_service_rejects_bad_scaling() -> None:
    with pytest.raises(ValidationError, match="max_instances"):
        _service(min_instances=5, max_instances=1)


def test_service_requires_vpc_connector_for_egress() -> None:
    with pytest.raises(ValidationError, match="vpc_egress requires vpc_connector"):
        _service(vpc_egress="ALL_TRAFFIC")


def test_service_rejects_invalid_env_key() -> None:
    with pytest.raises(ValidationError, match="environment variable names"):
        _service(env={"bad-key": "value"})


def test_function_rejects_bad_source_bucket() -> None:
    with pytest.raises(ValidationError, match="unknown source buckets"):
        _stack(cloud_run_functions=[_function(source_bucket="missing")])


def test_duplicate_service_names_raise() -> None:
    stack = _stack(cloud_run_services=[_service(), _service()])

    with pytest.raises(RenderError, match="duplicate resource address"):
        GcpRenderer(".tofu").render_text(stack)


# ── Artifact Registry / jobs ──────────────────────────────────────────
def test_artifact_repository_renders() -> None:
    repository = ArtifactRegistryRepository(
        project=PROJECT,
        repository_id="cloudrun-test",
        location="us-central1",
    )
    text = _main(_stack(artifact_registry_repositories=[repository]))

    assert 'resource "google_artifact_registry_repository" "repo_cloudrun_test"' in text
    assert 'repository_id = "cloudrun-test"' in text
    assert 'format        = "DOCKER"' in text


def test_job_renders_command_and_resources() -> None:
    job = CloudRunJob(
        project=PROJECT,
        name="runner",
        image="us-central1-docker.pkg.dev/demo-project/repo/app:tag",
        command=["python", "-c", "print('ok')"],
        env={"MODE": "batch"},
    )
    text = _main(_stack(cloud_run_jobs=[job]))

    assert 'resource "google_cloud_run_v2_job" "job_runner"' in text
    assert "command" in text and '"python"' in text and "print" in text
    assert "deletion_protection = true" in text
    assert "task_count  = 1" in text or "task_count" in text
    assert "parallelism" in text
    assert "max_retries" in text
    assert '"512Mi"' in text


def test_job_rejects_parallelism_above_task_count() -> None:
    with pytest.raises(ValidationError, match="parallelism"):
        CloudRunJob(
            project=PROJECT,
            name="runner",
            image="image",
            task_count=1,
            parallelism=2,
        )


# ── Volumes ───────────────────────────────────────────────────────────
def test_service_volumes_render_mounts_and_sources() -> None:
    service = _service(
        volumes=[
            Volume(
                name="scratch",
                mount_path="/tmp/scratch",
                empty_dir=EmptyDirVolume(size_limit="256Mi"),
            ),
            Volume(
                name="assets",
                mount_path="/mnt/assets",
                gcs=GcsVolume(bucket="demo-assets", read_only=True),
            ),
            Volume(
                name="creds",
                mount_path="/etc/creds",
                secret=SecretVolume(secret="db-password"),
            ),
            Volume(
                name="share",
                mount_path="/mnt/share",
                nfs=NfsVolume(server="10.0.0.2", path="/exports"),
            ),
            Volume(
                name="db",
                mount_path="/cloudsql",
                cloud_sql=CloudSqlVolume(instances=["proj:us-central1:pg"]),
            ),
        ]
    )
    text = _main(_stack(cloud_run_services=[service]))

    assert '"scratch"' in text and '"/tmp/scratch"' in text
    assert "empty_dir" in text and '"256Mi"' in text
    assert "gcs" in text and '"demo-assets"' in text
    assert "secret {" in text and '"db-password"' in text
    assert '"10.0.0.2"' in text
    assert '["proj:us-central1:pg"]' in text


def test_volume_requires_exactly_one_source() -> None:
    with pytest.raises(ValidationError, match="exactly one source"):
        Volume(name="empty", mount_path="/mnt/empty")

    with pytest.raises(ValidationError, match="exactly one source"):
        Volume(
            name="both",
            mount_path="/mnt/both",
            empty_dir=EmptyDirVolume(),
            gcs=GcsVolume(bucket="b"),
        )


def test_volume_rejects_duplicate_names_and_paths() -> None:
    with pytest.raises(ValidationError, match="duplicate volume names"):
        _service(
            volumes=[
                Volume(name="data", mount_path="/a", empty_dir=EmptyDirVolume()),
                Volume(name="data", mount_path="/b", empty_dir=EmptyDirVolume()),
            ]
        )

    with pytest.raises(ValidationError, match="duplicate volume mount paths"):
        _service(
            volumes=[
                Volume(name="one", mount_path="/same", empty_dir=EmptyDirVolume()),
                Volume(name="two", mount_path="/same", empty_dir=EmptyDirVolume()),
            ]
        )


def test_cloud_sql_volume_must_mount_at_cloudsql() -> None:
    with pytest.raises(ValidationError, match="/cloudsql"):
        Volume(
            name="db",
            mount_path="/data",
            cloud_sql=CloudSqlVolume(instances=["proj:us-central1:pg"]),
        )


def test_volume_mount_path_must_be_absolute() -> None:
    with pytest.raises(ValidationError, match="absolute"):
        Volume(name="data", mount_path="relative", empty_dir=EmptyDirVolume())


def test_gcs_mount_options_reject_leading_dashes() -> None:
    with pytest.raises(ValidationError, match="leading dashes"):
        GcsVolume(bucket="b", mount_options=["-o", "implicit-dirs"])


# ── Probes ────────────────────────────────────────────────────────────
def test_http_probes_render() -> None:
    service = _service(
        startup_probe=Probe(
            http_get=HttpProbe(path="/healthz", headers={"X-Probe": "startup"}),
            period_seconds=5,
            timeout_seconds=2,
            failure_threshold=6,
        ),
        liveness_probe=Probe(tcp_socket=TcpProbe(port=8080), period_seconds=30),
    )
    text = _main(_stack(cloud_run_services=[service]))

    assert "startup_probe {" in text
    assert '"/healthz"' in text
    assert '"X-Probe"' in text and '"startup"' in text
    assert "failure_threshold" in text and "6" in text
    assert "liveness_probe {" in text
    assert "tcp_socket" in text


def test_probe_requires_one_check_kind() -> None:
    with pytest.raises(ValidationError, match="exactly one of"):
        Probe()

    with pytest.raises(ValidationError, match="exactly one of"):
        Probe(http_get=HttpProbe(), tcp_socket=TcpProbe())


def test_probe_timeout_must_be_below_period() -> None:
    with pytest.raises(ValidationError, match="timeout_seconds"):
        Probe(http_get=HttpProbe(), timeout_seconds=10, period_seconds=10)


def test_startup_probe_period_is_capped() -> None:
    with pytest.raises(ValidationError, match="startup probe period_seconds"):
        _service(startup_probe=Probe(http_get=HttpProbe(), period_seconds=241))


# ── Worker pools ──────────────────────────────────────────────────────
def test_worker_pool_renders_hardened_defaults() -> None:
    pool = CloudRunWorkerPool(
        project=PROJECT,
        name="worker",
        image="us-central1-docker.pkg.dev/demo-project/repo/app@sha256:abc",
    )
    text = _main(_stack(cloud_run_worker_pools=[pool]))

    assert 'resource "google_cloud_run_v2_worker_pool" "pool_worker"' in text
    assert 'scaling_mode          = "MANUAL"' in text
    assert "manual_instance_count = 1" in text
    assert "deletion_protection = true" in text
    assert "ingress" not in text
    assert "ports" not in text


def test_worker_pool_renders_command_env_and_volumes() -> None:
    pool = CloudRunWorkerPool(
        project=PROJECT,
        name="worker",
        image="image",
        command=["python", "-m", "worker"],
        args=["--queue", "jobs"],
        env={"MODE": "pool"},
        manual_instance_count=2,
        volumes=[
            Volume(name="scratch", mount_path="/tmp/w", empty_dir=EmptyDirVolume()),
            Volume(name="raw", mount_path="/mnt/raw", gcs=GcsVolume(bucket="demo-raw")),
        ],
    )
    text = _main(_stack(cloud_run_worker_pools=[pool]))

    assert '"python"' in text and "worker" in text
    assert 'name  = "MODE"' in text
    assert "manual_instance_count = 2" in text
    assert 'mount_path = "/tmp/w"' in text
    assert 'bucket    = "demo-raw"' in text


def test_worker_pool_automatic_scaling_renders_bounds() -> None:
    pool = CloudRunWorkerPool(
        project=PROJECT,
        name="worker",
        image="image",
        scaling_mode="automatic",
        min_instances=1,
        max_instances=4,
    )
    text = _main(_stack(cloud_run_worker_pools=[pool]))

    assert '"AUTOMATIC"' in text
    assert "min_instance_count = 1" in text
    assert "max_instance_count = 4" in text
    assert "manual_instance_count" not in text


def test_worker_pool_rejects_bad_scaling_and_names() -> None:
    with pytest.raises(ValidationError, match="max_instances"):
        CloudRunWorkerPool(
            project=PROJECT,
            name="worker",
            image="image",
            scaling_mode="automatic",
            min_instances=4,
            max_instances=2,
        )

    with pytest.raises(ValidationError, match="worker pool names"):
        CloudRunWorkerPool(project=PROJECT, name="Bad_Name", image="image")


def test_duplicate_worker_pools_raise() -> None:
    pool = CloudRunWorkerPool(project=PROJECT, name="worker", image="image")
    with pytest.raises(RenderError, match="worker pool"):
        _main(_stack(cloud_run_worker_pools=[pool, pool]))
