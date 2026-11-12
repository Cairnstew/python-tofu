from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from python_tofu.core.limits import LimitMode
from python_tofu.core.models import PruneConfig
from python_tofu.providers.gcp import (
    BackendConfig,
    CloudRunFunction,
    CloudRunJob,
    CloudRunService,
    CloudRunWorkerPool,
    GcpProvider,
    GcpStack,
)
from python_tofu.providers.gcp.renderer import GcpRenderer

PROJECT = "demo-project"


def _service(**overrides: Any) -> CloudRunService:
    values: dict[str, Any] = {
        "project": PROJECT,
        "name": "hello",
        "image": "us-docker.pkg.dev/cloudrun/container/hello",
    }
    values.update(overrides)
    return CloudRunService(**values)  # type: ignore[arg-type]


def _function(**overrides: Any) -> CloudRunFunction:
    values: dict[str, Any] = {
        "project": PROJECT,
        "name": "hello-fn",
        "runtime": "python312",
        "entry_point": "hello_http",
        "source_bucket": "demo-source",
        "source_object": "hello.zip",
    }
    values.update(overrides)
    return CloudRunFunction(**values)  # type: ignore[arg-type]


def _stack(**overrides: Any) -> GcpStack:
    values: dict[str, Any] = {
        "provider": GcpProvider(project=PROJECT),
        "external_buckets": ["demo-source"],
        "cloud_run_services": [_service()],
        "cloud_run_functions": [_function()],
        "cloud_run_jobs": [CloudRunJob(project=PROJECT, name="batch", image="busybox")],
        "cloud_run_worker_pools": [
            CloudRunWorkerPool(project=PROJECT, name="worker", image="busybox")
        ],
    }
    values.update(overrides)
    return GcpStack(**values)  # type: ignore[arg-type]


def _main(stack: GcpStack) -> str:
    return " ".join(GcpRenderer(".tofu").render_text(stack)["main.tf"].split())


def test_default_profile_changes_nothing() -> None:
    plain = _stack()
    explicit = _stack(profile="default")

    assert _main(plain) == _main(explicit)
    assert plain.prune.enabled is False
    assert plain.limits_mode is None
    assert "ephemeral" not in plain.provider.default_labels
    assert "deletion_protection = true" in _main(plain)


def test_preview_flips_deletion_protection_on_every_supported_resource() -> None:
    stack = _stack(profile="preview")
    text = _main(stack)

    assert text.count("deletion_protection = false") == 3
    assert "deletion_protection = true" not in text


def test_preview_respects_explicit_deletion_protection() -> None:
    stack = _stack(profile="preview", cloud_run_services=[_service(deletion_protection=True)])

    assert "deletion_protection = true" in _main(stack)


def test_preview_enables_prune_limits_warn_and_the_ephemeral_label() -> None:
    stack = _stack(profile="preview")

    assert stack.prune.enabled is True
    assert stack.limits_mode is LimitMode.WARN
    assert stack.provider.default_labels == {"ephemeral": "true"}


def test_preview_keeps_explicit_prune_and_labels() -> None:
    stack = _stack(
        profile="preview",
        prune=PruneConfig(enabled=False),
        provider=GcpProvider(project=PROJECT, default_labels={"team": "core"}),
    )

    assert stack.prune.enabled is False
    assert stack.provider.default_labels == {"team": "core", "ephemeral": "true"}


def test_preview_keeps_an_explicit_limits_mode() -> None:
    stack = _stack(profile="preview", limits_mode=LimitMode.ERROR)

    assert stack.limits_mode is LimitMode.ERROR


def test_preview_switches_an_implicit_gcs_backend_to_local() -> None:
    stack = _stack(profile="preview", backend=BackendConfig(bucket="demo-state"))

    assert stack.backend is not None
    assert stack.backend.kind == "local"
    assert stack.backend.path == "terraform.tfstate"
    assert 'backend "local"' in GcpRenderer(".tofu").render_text(stack)["versions.tf"]


def test_preview_keeps_an_explicit_backend_kind() -> None:
    stack = _stack(
        profile="preview",
        backend=BackendConfig(kind="gcs", bucket="demo-state", prefix="team/state"),
    )

    assert stack.backend is not None
    assert stack.backend.kind == "gcs"
    assert 'backend "gcs"' in GcpRenderer(".tofu").render_text(stack)["versions.tf"]


# ── stack-level limit mode ────────────────────────────────────────────
def _over_limit_config(tmp_path: Path, *, limit_mode: str = "") -> Path:
    line = f'    limits_mode="{limit_mode}",\n' if limit_mode else ""
    path = tmp_path / "over.py"
    path.write_text(
        f"""\
from python_tofu import GcpProvider, GcpStack, StorageBucket

stack = GcpStack(
    provider=GcpProvider(project="{PROJECT}"),
{line}    buckets=[StorageBucket(
        project="{PROJECT}",
        name="demo-artifacts",
        location="us-central1",
        estimated_size_gb=9,
    )],
)
""",
        encoding="utf-8",
    )
    return path


def test_stack_limits_mode_warn_downgrades_a_blocking_limit(cli, runner, tmp_path: Path) -> None:
    config = _over_limit_config(tmp_path, limit_mode="warn")

    result = runner.invoke(
        cli,
        ["render", "--config", str(config), "--workdir", str(tmp_path / "w")],
    )

    assert result.exit_code == 0, result.output
    assert "Warning: gcp.storage.standard_gb" in result.output


def test_stack_limits_mode_default_still_blocks(cli, runner, tmp_path: Path) -> None:
    config = _over_limit_config(tmp_path)

    result = runner.invoke(
        cli,
        ["render", "--config", str(config), "--workdir", str(tmp_path / "w")],
    )

    assert result.exit_code == 1
    assert "always-free tier exceeded" in result.output


@pytest.mark.parametrize("profile", ["preview", "default"])
def test_profile_value_is_validated(profile: str) -> None:
    stack = GcpStack(provider=GcpProvider(project=PROJECT), profile=profile)  # type: ignore[arg-type]

    assert stack.profile.value == profile
