"""Canonical Google API service names and the protected baseline.

Kept in a leaf module so models, API derivation and pruning can share the
names without importing each other.
"""

from __future__ import annotations

SERVICE_USAGE = "serviceusage.googleapis.com"
CLOUD_RESOURCE_MANAGER = "cloudresourcemanager.googleapis.com"
IAM = "iam.googleapis.com"
IAM_CREDENTIALS = "iamcredentials.googleapis.com"
STORAGE = "storage.googleapis.com"
ARTIFACT_REGISTRY = "artifactregistry.googleapis.com"
RUN = "run.googleapis.com"
CLOUDFUNCTIONS = "cloudfunctions.googleapis.com"
CLOUDBUILD = "cloudbuild.googleapis.com"
EVENTARC = "eventarc.googleapis.com"
PUBSUB = "pubsub.googleapis.com"
CLOUD_BILLING = "cloudbilling.googleapis.com"
BILLING_BUDGETS = "billingbudgets.googleapis.com"
SECRET_MANAGER = "secretmanager.googleapis.com"  # nosec B105 - API service name, not a secret
CLOUD_SQL = "sqladmin.googleapis.com"
CLOUD_ASSET = "cloudasset.googleapis.com"
LOGGING = "logging.googleapis.com"
MONITORING = "monitoring.googleapis.com"

#: Control-plane APIs every owned project keeps: the wrapper needs them to
#: manage services, IAM, state, billing and live inventory, and workloads need
#: logging/monitoring. ``GcpProvider(default_apis=...)`` can add to this set,
#: but pruning never removes these.
DEFAULT_APIS: tuple[str, ...] = (
    SERVICE_USAGE,
    CLOUD_RESOURCE_MANAGER,
    IAM,
    IAM_CREDENTIALS,
    STORAGE,
    CLOUD_BILLING,
    BILLING_BUDGETS,
    CLOUD_ASSET,
    LOGGING,
    MONITORING,
)

#: Backwards-compatible name used by the prune module.
PROTECTED_APIS = DEFAULT_APIS

__all__ = [
    "ARTIFACT_REGISTRY",
    "BILLING_BUDGETS",
    "CLOUD_ASSET",
    "CLOUD_BILLING",
    "CLOUDBUILD",
    "CLOUDFUNCTIONS",
    "CLOUD_RESOURCE_MANAGER",
    "CLOUD_SQL",
    "DEFAULT_APIS",
    "EVENTARC",
    "IAM",
    "IAM_CREDENTIALS",
    "LOGGING",
    "MONITORING",
    "PROTECTED_APIS",
    "PUBSUB",
    "RUN",
    "SECRET_MANAGER",
    "SERVICE_USAGE",
    "STORAGE",
]
