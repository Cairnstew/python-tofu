"""Google Cloud always-free tier as a provider :class:`LimitPolicy`.

Source: https://cloud.google.com/free/docs/free-cloud-features (read 2026-11-10).
Free Tier limits are per **billing account** (Firestore and Logging are per
project). A stack usually describes one project, so declare amounts for the
whole billing account in ``GcpStack.usage_estimates`` when you need an accurate
check.

Keys are stable strings; the GCP measurement fills what it can derive from the
stack (currently eligible bucket storage) and otherwise trusts
``usage_estimates``. :mod:`python_tofu.providers.gcp.live` measures existing
infrastructure for the countable limits; byte-based limits still need estimates.
"""

from __future__ import annotations

from python_tofu.core.limits import (
    AggregateLimit,
    Limit,
    LimitAction,
    LimitMode,
    LimitPeriod,
    LimitPolicy,
    Usage,
)
from python_tofu.providers.gcp.stack import GcpStack

# Free Tier Cloud Storage only applies in these regions.
FREE_STORAGE_LOCATIONS = frozenset({"us-east1", "us-west1", "us-central1"})

_GCP_FREE_TIER_LIMITS: tuple[Limit, ...] = (
    # Storage
    Limit("gcp.storage.standard_gb", "storage", "GB", 5, description="Regional storage, US only"),
    Limit("gcp.storage.class_a_ops", "storage", "operations", 5_000),
    Limit("gcp.storage.class_b_ops", "storage", "operations", 50_000),
    Limit("gcp.storage.egress_gb", "storage", "GB", 100, description="North America egress"),
    # Compute
    Limit(
        "gcp.compute.e2_micro_hours",
        "compute",
        "hours",
        720,
        description="One e2-micro; conservative 30-day month (February is shorter)",
    ),
    Limit(
        "gcp.compute.standard_pd_gb", "compute", "GB", 30, description="Standard persistent disk"
    ),
    Limit("gcp.compute.egress_gb", "compute", "GB", 1, description="North America egress"),
    # BigQuery
    Limit("gcp.bigquery.query_tib", "bigquery", "TiB", 1),
    Limit("gcp.bigquery.storage_gib", "bigquery", "GiB", 10),
    # Cloud Run
    Limit("gcp.cloud_run.requests", "cloud_run", "requests", 2_000_000),
    Limit("gcp.cloud_run.gb_seconds", "cloud_run", "GB-seconds", 360_000),
    Limit("gcp.cloud_run.vcpu_seconds", "cloud_run", "vCPU-seconds", 180_000),
    Limit("gcp.cloud_run.egress_gb", "cloud_run", "GB", 1, description="North America egress"),
    # Cloud Run functions
    Limit("gcp.cloud_functions.invocations", "functions", "invocations", 2_000_000),
    Limit("gcp.cloud_functions.gb_seconds", "functions", "GB-seconds", 400_000),
    Limit("gcp.cloud_functions.ghz_seconds", "functions", "GHz-seconds", 200_000),
    Limit("gcp.cloud_functions.egress_gb", "functions", "GB", 5),
    # Firestore (per project)
    Limit("gcp.firestore.storage_gib", "firestore", "GiB", 1, LimitPeriod.TOTAL),
    Limit("gcp.firestore.reads_per_day", "firestore", "reads", 50_000, LimitPeriod.DAY),
    Limit("gcp.firestore.writes_per_day", "firestore", "writes", 20_000, LimitPeriod.DAY),
    Limit("gcp.firestore.deletes_per_day", "firestore", "deletes", 20_000, LimitPeriod.DAY),
    Limit("gcp.firestore.egress_gib", "firestore", "GiB", 10),
    # Pub/Sub
    Limit("gcp.pubsub.messages_gib", "pubsub", "GiB", 10),
    # GKE
    Limit(
        "gcp.gke.free_clusters", "gke", "clusters", 1, description="One Autopilot or zonal Standard"
    ),
    # Secret Manager
    Limit("gcp.secret_manager.active_versions", "secret_manager", "versions", 6),
    Limit("gcp.secret_manager.access_ops", "secret_manager", "operations", 10_000),
    Limit("gcp.secret_manager.rotation_notifications", "secret_manager", "notifications", 3),
    # Artifact Registry / Cloud Build
    Limit("gcp.artifact_registry.storage_gb", "artifact_registry", "GB", 0.5),
    Limit(
        "gcp.cloud_build.minutes",
        "cloud_build",
        "build-minutes",
        2_500,
        description="e2-standard-2",
    ),
    # Observability
    Limit("gcp.logging.log_gib", "logging", "GiB", 50, description="Per project"),
    Limit("gcp.monitoring.timeseries_read", "monitoring", "time series", 1_000_000),
    # KMS
    Limit("gcp.kms.active_key_versions", "kms", "key versions", 100, description="Autokey only"),
    Limit("gcp.kms.crypto_ops", "kms", "operations", 10_000),
    # Workflows / integration / data
    Limit("gcp.workflows.internal_steps", "workflows", "steps", 5_000),
    Limit("gcp.workflows.external_calls", "workflows", "calls", 2_000),
    Limit("gcp.application_integration.executions", "integration", "executions", 400),
    Limit("gcp.application_integration.data_gib", "integration", "GiB", 20),
    Limit("gcp.datastream.cdc_gib", "datastream", "GiB", 100),
    # Source repositories / shell
    Limit("gcp.source_repos.users", "source_repos", "users", 5),
    Limit("gcp.source_repos.storage_gb", "source_repos", "GB", 50),
    Limit("gcp.source_repos.egress_gb", "source_repos", "GB", 50),
    Limit("gcp.cloud_shell.disk_gb", "cloud_shell", "GB", 5, LimitPeriod.TOTAL),
    # App Engine (daily)
    Limit("gcp.app_engine.f1_hours_per_day", "app_engine", "hours", 28, LimitPeriod.DAY),
    Limit("gcp.app_engine.b1_hours_per_day", "app_engine", "hours", 9, LimitPeriod.DAY),
    Limit("gcp.app_engine.egress_gb_per_day", "app_engine", "GB", 1, LimitPeriod.DAY),
    # Pre-trained APIs
    Limit("gcp.natural_language.units", "ai_api", "units", 5_000),
    Limit("gcp.vision.units", "ai_api", "units", 1_000),
    Limit("gcp.video_intelligence.units", "ai_api", "units", 1_000),
    Limit("gcp.speech.minutes", "ai_api", "minutes", 60),
    Limit("gcp.recaptcha.assessments", "ai_api", "assessments", 10_000),
    Limit("gcp.web_risk.calls", "ai_api", "calls", 100_000),
    # Misc
    Limit("gcp.workload_manager.evaluations", "misc", "evaluations", 5_000),
    Limit("gcp.cloud_deploy.active_pipelines", "misc", "pipelines", 1),
)

GCP_FREE_TIER = LimitPolicy(
    limits=_GCP_FREE_TIER_LIMITS,
    aggregates=(
        AggregateLimit(
            key="gcp.free_tier.total",
            amount=1.0,
            action=LimitAction.WARN,
            description="Sum of normalised usage across every free-tier limit",
        ),
    ),
    default_mode=LimitMode.ERROR,
    description="Google Cloud always-free tier",
)


def measure_usage(stack: GcpStack) -> Usage:
    """Derive what the stack knows and trust explicit estimates for the rest."""

    usage = Usage.from_mapping(stack.usage_estimates)

    eligible_storage_gb = sum(
        bucket.estimated_size_gb
        for bucket in stack.buckets
        if bucket.location.lower() in FREE_STORAGE_LOCATIONS
    )
    return usage.add("gcp.storage.standard_gb", eligible_storage_gb)


__all__ = ["FREE_STORAGE_LOCATIONS", "GCP_FREE_TIER", "measure_usage"]
