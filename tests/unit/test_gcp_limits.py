from __future__ import annotations

import pytest
from pydantic import ValidationError

from python_tofu.core.limits import LimitPeriod
from python_tofu.providers.gcp import GCP, GcpProvider, GcpStack, StorageBucket
from python_tofu.providers.gcp.limits import (
    FREE_STORAGE_LOCATIONS,
    GCP_FREE_TIER,
    measure_usage,
)
from python_tofu.providers.gcp.live import live_measure_usage
from python_tofu.providers.gcp.renderer import GcpRenderer


def test_gcp_provider_is_wired_to_the_free_tier_policy() -> None:
    assert GCP.limit_policy is GCP_FREE_TIER
    assert GCP.measure_usage is measure_usage
    assert GCP.live_measure_usage is live_measure_usage
    assert GCP.has_live_measurement is True
    assert GCP_FREE_TIER.default_mode.value == "error"


def test_free_tier_catalog_contains_current_headline_limits() -> None:
    expected = {
        "gcp.storage.standard_gb": 5,
        "gcp.storage.class_a_ops": 5_000,
        "gcp.compute.e2_micro_hours": 720,
        "gcp.bigquery.query_tib": 1,
        "gcp.bigquery.storage_gib": 10,
        "gcp.firestore.reads_per_day": 50_000,
        "gcp.cloud_run.requests": 2_000_000,
        "gcp.secret_manager.active_versions": 6,
        "gcp.gke.free_clusters": 1,
    }
    for key, amount in expected.items():
        assert GCP_FREE_TIER.get(key).amount == amount


def test_total_allowances_and_monitoring_area() -> None:
    # Firestore storage and Cloud Shell disk are standing allowances, not
    # monthly resets; Monitoring's time-series read is its own area.
    assert GCP_FREE_TIER.get("gcp.firestore.storage_gib").period is LimitPeriod.TOTAL
    assert GCP_FREE_TIER.get("gcp.cloud_shell.disk_gb").period is LimitPeriod.TOTAL
    assert GCP_FREE_TIER.get("gcp.monitoring.timeseries_read").area == "monitoring"


def test_measure_usage_sums_only_free_tier_regions() -> None:
    stack = GcpStack(
        provider=GcpProvider(project="demo-project"),
        buckets=[
            StorageBucket(
                project="demo-project",
                name="free-artifacts",
                location="us-central1",
                estimated_size_gb=3,
            ),
            StorageBucket(
                project="demo-project",
                name="paid-artifacts",
                location="europe-west4",
                estimated_size_gb=100,
            ),
        ],
        usage_estimates={"gcp.bigquery.query_tib": 0.25},
    )
    usage = measure_usage(stack)
    assert usage.get("gcp.storage.standard_gb") == 3
    assert usage.get("gcp.bigquery.query_tib") == 0.25
    assert {"us-central1", "us-east1", "us-west1"} == set(FREE_STORAGE_LOCATIONS)


def test_usage_estimates_are_merged_with_measured_values() -> None:
    stack = GcpStack(
        provider=GcpProvider(project="demo-project"),
        buckets=[
            StorageBucket(
                project="demo-project",
                name="free-artifacts",
                location="us-west1",
                estimated_size_gb=2,
            )
        ],
        usage_estimates={"gcp.storage.standard_gb": 1.5},
    )
    assert measure_usage(stack).get("gcp.storage.standard_gb") == 3.5


def test_free_tier_storage_violation_is_an_error() -> None:
    stack = GcpStack(
        provider=GcpProvider(project="demo-project"),
        buckets=[
            StorageBucket(
                project="demo-project",
                name="too-big",
                location="us-east1",
                estimated_size_gb=6,
            )
        ],
    )
    report = GCP.throttler().check(GCP.usage(stack))
    assert [check.key for check in report.errors] == ["gcp.storage.standard_gb"]


def test_aggregate_summarises_usage_across_areas() -> None:
    usage = {"gcp.storage.standard_gb": 5, "gcp.bigquery.query_tib": 1}
    report = GCP.throttler().check(usage)
    total = next(check for check in report.checks if check.key == "gcp.free_tier.total")
    assert total.used == pytest.approx(2.0)
    assert total.exceeded is True
    # The aggregate is a warning by default, so it does not block.
    assert total.key not in {check.key for check in report.errors}


def test_negative_estimates_are_rejected() -> None:
    with pytest.raises(ValidationError, match="non-negative"):
        GcpStack(
            provider=GcpProvider(project="demo-project"),
            usage_estimates={"gcp.storage.standard_gb": -1},
        )
    with pytest.raises(ValidationError):
        StorageBucket(project="demo-project", name="demo-bucket", estimated_size_gb=-1)


def test_estimate_fields_are_not_rendered_as_hcl() -> None:
    stack = GcpStack(
        provider=GcpProvider(project="demo-project"),
        buckets=[
            StorageBucket(
                project="demo-project",
                name="demo-artifacts",
                estimated_size_gb=42,
            )
        ],
    )
    main = GcpRenderer(".tofu").render_text(stack)["main.tf"]
    assert "estimated_size_gb" not in main
