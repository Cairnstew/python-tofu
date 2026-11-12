"""Discover live GCP resources that a :class:`GcpStack` does not declare.

Pruning is the inverse of rendering: the renderer writes exactly the declared
resources, and this module finds the rest in Cloud Asset Inventory so
:class:`python_tofu.core.prune.Reaper` can adopt and destroy them.

Only sections that OpenTofu can import safely are supported:

- ``buckets``          — ``google_storage_bucket`` (import id ``project/name``)
- ``subscriptions``    — ``google_pubsub_subscription`` (before topics, which need them gone)
- ``topics``           — ``google_pubsub_topic``
- ``service_accounts`` — ``google_service_account`` (Google-managed defaults skipped)
- ``apis``             — ``google_project_service`` (essential APIs protected)

Discovery uses the service's own read API (Storage, IAM, Service Usage) rather
than Cloud Asset Inventory: CAI is eventually consistent, so a bucket deleted a
moment ago can still appear and make the next prune try to import a 404.

Bucket objects cannot be imported by the provider, and project IAM bindings are
left alone because an authoritative IAM sweep can remove human access. Both are
deliberately outside the supported section list.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from python_tofu.core.prune import PrunableResource, PrunePlan
from python_tofu.providers.gcp.apis import declared_apis
from python_tofu.providers.gcp.live import access_token, get_json
from python_tofu.providers.gcp.models import (
    GCP_PRUNE_SECTIONS,
    DeadLetter,
    ProjectApi,
    PubSubSubscription,
    PubSubTopic,
    RetryPolicy,
    ServiceAccount,
    StorageBucket,
    StorageClass,
)
from python_tofu.providers.gcp.quirks import slug
from python_tofu.providers.gcp.renderer import (
    _api_block,
    _bucket_block,
    _pubsub_subscription_block,
    _pubsub_topic_block,
    _service_account_block,
)
from python_tofu.providers.gcp.stack import GcpStack

PRUNE_SECTIONS = GCP_PRUNE_SECTIONS

STORAGE_BASE = "https://storage.googleapis.com/storage/v1"
IAM_BASE = "https://iam.googleapis.com/v1"
SERVICE_USAGE_BASE = "https://serviceusage.googleapis.com/v1"
PUBSUB_BASE = "https://pubsub.googleapis.com/v1"

#: APIs the wrapper or the cloud itself needs to finish a prune; never disable.
PROTECTED_APIS = frozenset(
    {
        "billingbudgets.googleapis.com",
        "cloudasset.googleapis.com",
        "cloudresourcemanager.googleapis.com",
        "iam.googleapis.com",
        "iamcredentials.googleapis.com",
        "logging.googleapis.com",
        "monitoring.googleapis.com",
        "serviceusage.googleapis.com",
        "storage.googleapis.com",
    }
)

#: Local parts of auto-created service accounts (compute, appspot, agents, ...).
_DEFAULT_ACCOUNT_RE = re.compile(r"^(?:\d+|\d+-compute|service-\d+|cloudservices)$")

_STORAGE_CLASSES: dict[str, StorageClass] = {
    "STANDARD": "STANDARD",
    "NEARLINE": "NEARLINE",
    "COLDLINE": "COLDLINE",
    "ARCHIVE": "ARCHIVE",
    "MULTI_REGIONAL": "MULTI_REGIONAL",
    "REGIONAL": "REGIONAL",
    "DURABLE_REDUCED_AVAILABILITY": "DURABLE_REDUCED_AVAILABILITY",
}


def _storage_class(value: Any) -> StorageClass:
    return _STORAGE_CLASSES.get(str(value or "").upper(), "STANDARD")


def _paged(url: str, token: str, params: dict[str, str], key: str) -> list[dict[str, Any]]:
    """Follow ``nextPageToken`` and return the ``key`` list from every page."""

    items: list[dict[str, Any]] = []
    query = dict(params)
    while True:
        payload = get_json(url, token, query)
        items.extend(payload.get(key, []))
        page = payload.get("nextPageToken")
        if not page:
            return items
        query = {**params, "pageToken": str(page)}


def list_buckets(project: str, token: str) -> list[dict[str, Any]]:
    return _paged(f"{STORAGE_BASE}/b", token, {"project": project}, "items")


def list_service_accounts(project: str, token: str) -> list[dict[str, Any]]:
    return _paged(f"{IAM_BASE}/projects/{project}/serviceAccounts", token, {}, "accounts")


def list_services(project: str, token: str) -> list[dict[str, Any]]:
    return _paged(
        f"{SERVICE_USAGE_BASE}/projects/{project}/services",
        token,
        {"filter": "state:ENABLED"},
        "services",
    )


def list_topics(project: str, token: str) -> list[dict[str, Any]]:
    return _paged(f"{PUBSUB_BASE}/projects/{project}/topics", token, {}, "topics")


def list_subscriptions(project: str, token: str) -> list[dict[str, Any]]:
    return _paged(f"{PUBSUB_BASE}/projects/{project}/subscriptions", token, {}, "subscriptions")


def _public_access_prevention(value: Any) -> Literal["inherited", "enforced"]:
    return "enforced" if str(value or "").lower() == "enforced" else "inherited"


def _optional_text(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _basename(value: Any) -> str:
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def _is_managed_service_account(email: str, project: str) -> bool:
    """True for accounts GCP creates for itself; pruning those breaks services."""

    local, _, domain = email.partition("@")
    if domain != f"{project}.iam.gserviceaccount.com":
        return True
    return bool(_DEFAULT_ACCOUNT_RE.match(local))


def _topic_plan(stack: GcpStack, token: str) -> list[PrunableResource]:
    project = stack.provider.project
    declared = {topic.name for topic in stack.pubsub_topics} | set(stack.external_topics)
    found: list[PrunableResource] = []
    for data in list_topics(project, token):
        name = _basename(data.get("name"))
        if not name or name in declared:
            continue
        topic = PubSubTopic(
            project=project,
            name=name,
            message_retention_duration=_optional_text(data.get("messageRetentionDuration")),
            labels={str(k): str(v) for k, v in (data.get("labels") or {}).items()},
        )
        found.append(
            PrunableResource(
                section="topics",
                address=f"google_pubsub_topic.topic_{slug(name)}",
                import_id=f"projects/{project}/topics/{name}",
                block=_pubsub_topic_block(topic),
                description=f"topic {name}",
            )
        )
    return found


def _subscription_model(project: str, data: dict[str, Any]) -> PubSubSubscription:
    push = data.get("pushConfig") or {}
    oidc = push.get("oidcToken") or {}
    dead = data.get("deadLetterPolicy") or {}
    retry = data.get("retryPolicy") or {}
    retention = _optional_text(data.get("messageRetentionDuration"))
    expiration = (data.get("expirationPolicy") or {}).get("ttl") or "2678400s"
    return PubSubSubscription(
        project=project,
        name=_basename(data.get("name")),
        topic=_basename(data.get("topic")),
        ack_deadline_seconds=int(data.get("ackDeadlineSeconds") or 10),
        message_retention_duration=retention,
        retain_acked_messages=bool(data.get("retainAckedMessages", False)),
        expiration_ttl=str(expiration),
        filter=_optional_text(data.get("filter")),
        dead_letter=(
            DeadLetter(
                topic=_basename(dead.get("deadLetterTopic")),
                max_delivery_attempts=int(dead.get("maxDeliveryAttempts") or 5),
            )
            if dead
            else None
        ),
        retry=(
            RetryPolicy(
                minimum_backoff=str(retry.get("minimumBackoff") or "10s"),
                maximum_backoff=str(retry.get("maximumBackoff") or "600s"),
            )
            if retry
            else None
        ),
        enable_message_ordering=bool(data.get("enableMessageOrdering", False)),
        enable_exactly_once_delivery=bool(data.get("enableExactlyOnceDelivery", False)),
        push_endpoint=_optional_text(push.get("pushEndpoint")),
        push_service_account=_optional_text(oidc.get("serviceAccountEmail")),
        push_audience=_optional_text(oidc.get("audience")),
        labels={str(k): str(v) for k, v in (data.get("labels") or {}).items()},
    )


def _subscription_plan(stack: GcpStack, token: str) -> list[PrunableResource]:
    project = stack.provider.project
    declared = {subscription.name for subscription in stack.pubsub_subscriptions}
    found: list[PrunableResource] = []
    for data in list_subscriptions(project, token):
        name = _basename(data.get("name"))
        if not name or name in declared:
            continue
        subscription = _subscription_model(project, data)
        found.append(
            PrunableResource(
                section="subscriptions",
                address=f"google_pubsub_subscription.sub_{slug(name)}",
                import_id=f"projects/{project}/subscriptions/{name}",
                block=_pubsub_subscription_block(subscription, stack),
                description=f"subscription {name}",
            )
        )
    return found


def _bucket_plan(stack: GcpStack, token: str) -> list[PrunableResource]:
    project = stack.provider.project
    declared = {bucket.name for bucket in stack.buckets} | set(stack.external_buckets)
    found: list[PrunableResource] = []
    for data in list_buckets(project, token):
        name = _basename(data.get("name"))
        if not name or name in declared:
            continue
        iam = data.get("iamConfiguration") or {}
        uniform = (iam.get("uniformBucketLevelAccess") or {}).get("enabled", True)
        bucket = StorageBucket(
            project=project,
            name=name,
            location=str(data.get("location") or "US"),
            storage_class=_storage_class(data.get("storageClass")),
            uniform_bucket_level_access=bool(uniform),
            public_access_prevention=_public_access_prevention(iam.get("publicAccessPrevention")),
            force_destroy=True,
            versioning=bool((data.get("versioning") or {}).get("enabled")),
        )
        found.append(
            PrunableResource(
                section="buckets",
                address=f"google_storage_bucket.bucket_{slug(name)}",
                import_id=f"{project}/{name}",
                block=_bucket_block(bucket),
                description=f"bucket {name}",
            )
        )
    return found


def _service_account_plan(stack: GcpStack, token: str) -> list[PrunableResource]:
    project = stack.provider.project
    declared = {account.account_id for account in stack.service_accounts}
    found: list[PrunableResource] = []
    for data in list_service_accounts(project, token):
        email = str(data.get("email") or "")
        account_id = email.partition("@")[0]
        if not email or account_id in declared or _is_managed_service_account(email, project):
            continue
        account = ServiceAccount(
            project=project,
            account_id=account_id,
            display_name=_optional_text(data.get("displayName")),
            description=_optional_text(data.get("description")),
        )
        found.append(
            PrunableResource(
                section="service_accounts",
                address=f"google_service_account.sa_{slug(account_id)}",
                import_id=f"projects/{project}/serviceAccounts/{email}",
                block=_service_account_block(account),
                description=f"service account {email}",
            )
        )
    return found


def _api_plan(stack: GcpStack, token: str) -> list[PrunableResource]:
    project = stack.provider.project
    declared = {api.service for api in declared_apis(stack) if api.project == project}
    found: list[PrunableResource] = []
    for data in list_services(project, token):
        service = _basename(data.get("name"))
        if not service or service in declared:
            continue
        if str(data.get("state") or "ENABLED").upper() != "ENABLED":
            continue
        if service in PROTECTED_APIS:
            continue
        api = ProjectApi(project=project, service=service, disable_on_destroy=True)
        found.append(
            PrunableResource(
                section="apis",
                address=f"google_project_service.api_{slug(service)}",
                import_id=f"{project}/{service}",
                block=_api_block(api),
                description=f"API {service}",
            )
        )
    return found


def discover(stack: GcpStack, sections: tuple[str, ...]) -> PrunePlan:
    """Return live resources in ``sections`` that ``stack`` does not declare."""

    token = access_token(stack)
    resources: list[PrunableResource] = []
    warnings: list[str] = []
    project = stack.provider.project
    other_projects = sorted(
        ({item.project_id for item in stack.projects} | set(stack.external_projects)) - {project}
    )
    if other_projects:
        warnings.append(
            f"pruning only inspects {project}; other projects are left untouched: "
            + ", ".join(other_projects)
        )
    if "subscriptions" in sections:
        resources.extend(_subscription_plan(stack, token))
    if "topics" in sections:
        resources.extend(_topic_plan(stack, token))
    if "topics" in sections and "subscriptions" not in sections:
        warnings.append(
            "pruning topics without subscriptions can fail while a topic still has "
            "subscriptions; include the subscriptions section first"
        )
    if "buckets" in sections:
        resources.extend(_bucket_plan(stack, token))
    if "service_accounts" in sections:
        resources.extend(_service_account_plan(stack, token))
    if "apis" in sections:
        resources.extend(_api_plan(stack, token))
    if not resources:
        warnings.append("no undeclared resources found in the selected sections")
    return PrunePlan(resources=tuple(resources), warnings=tuple(warnings))


__all__ = [
    "PROTECTED_APIS",
    "PRUNE_SECTIONS",
    "discover",
    "list_buckets",
    "list_service_accounts",
    "list_services",
    "list_subscriptions",
    "list_topics",
]
