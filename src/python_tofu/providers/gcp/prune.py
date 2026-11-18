"""Discover live GCP resources that a :class:`GcpStack` does not declare.

Pruning is the inverse of rendering: the renderer writes exactly the declared
resources, and this module finds the rest in Cloud Asset Inventory so
:class:`python_tofu.core.prune.Reaper` can adopt and destroy them.

Only sections that OpenTofu can import safely are supported:

- ``buckets``          — ``google_storage_bucket`` (import id ``project/name``)
- ``subscriptions``    — ``google_pubsub_subscription`` (before topics, which need them gone)
- ``topics``           — ``google_pubsub_topic``
- ``service_accounts`` — ``google_service_account`` (Google-managed defaults skipped)
- ``apis``             — ``google_project_service`` (essential and dependency APIs protected)
- ``projects``         — ``google_project`` (only projects the provider provisioned; the
  organization, declared/external projects and the credential's project are never candidates;
  explicit opt-in only)

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

from python_tofu.core.exceptions import PruneError
from python_tofu.core.hcl import Attr, Block, body
from python_tofu.core.prune import PrunableResource, PrunePlan
from python_tofu.providers.gcp.apis import required_apis
from python_tofu.providers.gcp.live import (
    access_token,
    credential_identities,
    get_json,
    post_json,
)
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
from python_tofu.providers.gcp.service_names import DEFAULT_APIS
from python_tofu.providers.gcp.stack import GcpStack

PRUNE_SECTIONS = GCP_PRUNE_SECTIONS

STORAGE_BASE = "https://storage.googleapis.com/storage/v1"
IAM_BASE = "https://iam.googleapis.com/v1"
SERVICE_USAGE_BASE = "https://serviceusage.googleapis.com/v1"
PUBSUB_BASE = "https://pubsub.googleapis.com/v1"
CRM_BASE = "https://cloudresourcemanager.googleapis.com/v1"
CRM_FOLDERS_BASE = "https://cloudresourcemanager.googleapis.com/v2"

#: APIs the wrapper or the cloud itself needs to finish a prune; never disable.
#: ``GcpProvider.default_apis`` adds to this set (see ``_api_plan``).
PROTECTED_APIS = frozenset(DEFAULT_APIS)

#: Local parts of auto-created service accounts (compute, appspot, agents, ...).
_DEFAULT_ACCOUNT_RE = re.compile(r"^(?:\d+|\d+-compute|service-\d+|cloudservices)$")

#: Domain suffix of user-created service accounts; the project id is the prefix.
_SERVICE_ACCOUNT_SUFFIX = ".iam.gserviceaccount.com"

#: Label the Google provider stamps on resources it provisions.
ATTRIBUTION_LABEL = "goog-terraform-provisioned"

#: Permission needed to delete a project.
PROJECT_DELETE_PERMISSION = "resourcemanager.projects.delete"

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


def list_projects(token: str, parent: str) -> list[dict[str, Any]]:
    """Projects directly under ``organizations/<id>`` or ``folders/<id>``.

    The Resource Manager listing is filtered by parent type/id so the sweep stays
    inside one organization; projects in another organization are never listed.
    """

    kind, _, value = parent.partition("/")
    if kind not in ("organizations", "folders") or not value:
        raise ValueError(f"unsupported project parent {parent!r}")
    return _paged(
        f"{CRM_BASE}/projects",
        token,
        {"filter": f"parent.type:{kind.removesuffix('s')} parent.id:{value}"},
        "projects",
    )


def list_folders(parent: str, token: str) -> list[dict[str, Any]]:
    """Immediate child folders of an organization or folder."""

    return _paged(f"{CRM_FOLDERS_BASE}/folders", token, {"parent": parent}, "folders")


def list_org_projects(token: str, organization: str) -> list[dict[str, Any]]:
    """Every project under ``organization``, descending through folders."""

    scope = organization if "/" in organization else f"organizations/{organization}"
    projects = list_projects(token, scope)
    for folder in list_folders(scope, token):
        name = str(folder.get("name") or "")
        if name:
            projects.extend(list_org_projects(token, name))
    return projects


def project_organization(token: str, project: str) -> str | None:
    """Organization id from a project's ancestry, or ``None`` if it has none.

    ``getAncestry`` is a POST in the Resource Manager v1 API, not a GET.
    """

    payload = post_json(f"{CRM_BASE}/projects/{project}:getAncestry", token, {})
    for ancestor in payload.get("ancestor") or ():
        resource = ancestor.get("resourceId") or {}
        if resource.get("type") == "organization":
            return str(resource.get("id") or "") or None
    return None


def provisioned_by_tofu(data: dict[str, Any]) -> bool:
    """True when the provider marked the project as Terraform-provisioned.

    The Google provider adds ``goog-terraform-provisioned = "true"`` to resources
    it creates. A project without it was created by hand (console, gcloud, another
    tool), so the stack has no mandate to delete it.
    """

    labels = data.get("labels") or {}
    return str(labels.get(ATTRIBUTION_LABEL, "")).lower() == "true"


def can_delete_project(token: str, project: str) -> bool:
    """True when the active credential holds ``resourcemanager.projects.delete``."""

    payload = post_json(
        f"{CRM_BASE}/projects/{project}:testIamPermissions",
        token,
        {"permissions": [PROJECT_DELETE_PERMISSION]},
    )
    return PROJECT_DELETE_PERMISSION in (payload.get("permissions") or ())


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


def _protected_service_accounts(stack: GcpStack) -> frozenset[str]:
    """Account ids/emails prune must never delete.

    Always includes the active credential's own service-account identity (key
    ``client_email`` and impersonation target), regardless of the caller's
    ``include_service_accounts`` / ``--allow-service-accounts`` choice.
    """

    protected: set[str] = set()
    for item in stack.prune.protected_service_accounts:
        value = item.strip().lower()
        prefix = "serviceaccount:"
        if value.startswith(prefix):
            value = value[len(prefix) :]
        protected.add(value)
    protected.update(
        credential_identities(
            stack.provider.credentials,
            stack.provider.impersonate_service_account,
        )
    )
    return frozenset(protected)


def _service_account_plan(
    stack: GcpStack, token: str, protected: frozenset[str]
) -> list[PrunableResource]:
    project = stack.provider.project
    declared = {account.account_id for account in stack.service_accounts}
    found: list[PrunableResource] = []
    for data in list_service_accounts(project, token):
        email = str(data.get("email") or "")
        account_id = email.partition("@")[0]
        if not email or account_id in declared or _is_managed_service_account(email, project):
            continue
        if email.lower() in protected or account_id.lower() in protected:
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
    # Explicit entries plus every API a declared resource needs. Dependencies
    # stay declared even when ``auto_enable_apis=False``: disabling an API a
    # declared resource depends on would break the next apply, and the flag only
    # says the stack does not own enablement.
    declared = {api.service for api in stack.apis if api.project == project}
    declared.update(required_apis(stack).get(project, ()))
    found: list[PrunableResource] = []
    for data in list_services(project, token):
        service = _basename(data.get("name"))
        if not service or service in declared:
            continue
        if str(data.get("state") or "ENABLED").upper() != "ENABLED":
            continue
        if service in PROTECTED_APIS or service in stack.provider.default_apis:
            continue
        api = ProjectApi(
            project=project,
            service=service,
            disable_on_destroy=True,
            # Removing a service often requires removing its dependents first
            # (cloudapis, telemetry, geminicloudassist, ...). Prune is already
            # authoritative for the project, so let Service Usage cascade.
            disable_dependent_services=True,
        )
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


def _resolve_account_email(stack: GcpStack, value: str) -> str:
    """Resolve a declared account id to its generated email (emails pass through)."""

    if "@" in value:
        return value
    for account in stack.service_accounts:
        if account.account_id == value:
            return f"{account.account_id}@{account.project}.iam.gserviceaccount.com"
    return value


def _declared_project_iam(stack: GcpStack, project: str) -> set[tuple[str, str]]:
    """Project-level (role, member) pairs the typed stack declares."""

    declared: set[tuple[str, str]] = set()
    for binding in stack.iam_members:
        if binding.project != project:
            continue
        member = binding.member
        if binding.service_account is not None:
            member = f"serviceAccount:{_resolve_account_email(stack, binding.service_account)}"
        if member:
            declared.add((binding.role.lower(), member.lower()))
    for account in stack.service_accounts:
        if account.project != project:
            continue
        email = f"{account.account_id}@{account.project}.iam.gserviceaccount.com"
        for role in account.roles:
            declared.add((role.lower(), f"serviceAccount:{email}".lower()))
    return declared


def get_project_iam_bindings(project: str, token: str) -> list[dict[str, Any]]:
    """Return the project IAM policy bindings, including conditional ones."""

    payload = post_json(
        f"{CRM_BASE}/projects/{project}:getIamPolicy",
        token,
        {"options": {"requestedPolicyVersion": 3}},
    )
    bindings = payload.get("bindings")
    if not isinstance(bindings, list):
        return []
    return [item for item in bindings if isinstance(item, dict)]


def _project_iam_plan(
    stack: GcpStack, token: str, protected: frozenset[str]
) -> tuple[list[PrunableResource], dict[str, int], list[str]]:
    """Undeclared project bindings for service accounts declared in this stack.

    Anything else is reported and left alone: human/group/domain members,
    ``allUsers``, conditional bindings, protected roles, the active identity and
    service accounts the stack does not declare.
    """

    project = stack.provider.project
    declared = _declared_project_iam(stack, project)
    protected_roles = {role.lower() for role in stack.prune.protected_iam_roles}
    managed = {
        f"{account.account_id}@{account.project}.iam.gserviceaccount.com".lower()
        for account in stack.service_accounts
    }
    found: list[PrunableResource] = []
    skipped = {
        "non-service-account": 0,
        "not-declared": 0,
        "conditional": 0,
        "protected-role": 0,
        "protected-identity": 0,
    }
    details: list[str] = []

    def note(reason: str, role: str, member: str) -> None:
        details.append(f"{member} {role} ({reason})")

    for binding in get_project_iam_bindings(project, token):
        role = str(binding.get("role") or "")
        members = binding.get("members") or []
        if binding.get("condition"):
            for raw_member in members:
                skipped["conditional"] += 1
                note("conditional", role, str(raw_member))
            continue
        if role.lower() in protected_roles:
            for raw_member in members:
                skipped["protected-role"] += 1
                note("protected-role", role, str(raw_member))
            continue
        for raw_member in members:
            member = str(raw_member)
            if not member.startswith("serviceAccount:"):
                skipped["non-service-account"] += 1
                note("non-service-account", role, member)
                continue
            email = member.split(":", 1)[1].lower()
            account_id = email.partition("@")[0]
            if email in protected or account_id in protected:
                skipped["protected-identity"] += 1
                note("protected-identity", role, member)
                continue
            if email not in managed:
                skipped["not-declared"] += 1
                note("not-declared", role, member)
                continue
            if (role.lower(), member.lower()) in declared:
                continue
            label = f"prune_iam_{slug(role)}_{slug(member)}"
            found.append(
                PrunableResource(
                    section="project_iam",
                    address=f"google_project_iam_member.{label}",
                    import_id=f"{project} {role} {member}",
                    block=Block(
                        "resource",
                        ("google_project_iam_member", label),
                        body(
                            Attr("project", project),
                            Attr("role", role),
                            Attr("member", member),
                        ),
                    ),
                    description=f"IAM binding {role} for {member}",
                )
            )
    return found, skipped, details


def _protected_projects(stack: GcpStack) -> frozenset[str]:
    """Projects prune must never delete.

    Beyond the declared/external projects, this protects the provider project and
    the project that owns the active credential: deleting either would take the
    tool's own access away mid-run.
    """

    protected = {
        stack.provider.project,
        *stack.external_projects,
        *(project.project_id for project in stack.projects),
        *stack.prune.protected_projects,
    }
    identities = credential_identities(
        stack.provider.credentials,
        stack.provider.impersonate_service_account,
    )
    for email in identities:
        _, _, domain = email.partition("@")
        if domain.endswith(_SERVICE_ACCOUNT_SUFFIX):
            protected.add(domain.removesuffix(_SERVICE_ACCOUNT_SUFFIX))
    return frozenset(protected)


def _prune_project_block(project_id: str, name: str) -> Block:
    """Minimal ``google_project`` block for the scratch module.

    The adopt step imports the live project, so it must not edit it: only the
    identity fields and ``deletion_policy`` are configured, and every attribute
    that cannot be reconstructed faithfully (billing account, org/folder parent,
    labels, the provider's attribution label) is ignored. ``deletion_policy`` is
    applied on purpose: the provider defaults an imported project to
    ``PREVENT``, which would block the destroy.
    """

    return Block(
        "resource",
        ("google_project", f"project_{slug(project_id)}"),
        body(
            Attr("project_id", project_id),
            Attr("name", name),
            Attr("deletion_policy", "DELETE"),
            Block(
                "lifecycle",
                body=body(
                    Attr(
                        "ignore_changes",
                        [
                            "auto_create_network",
                            "billing_account",
                            "folder_id",
                            "labels",
                            "org_id",
                            "terraform_labels",
                        ],
                    )
                ),
            ),
        ),
    )


def _project_plan(
    stack: GcpStack, token: str
) -> tuple[list[PrunableResource], list[str], list[str]]:
    """Projects in the stack's organization that the stack does not declare.

    The organization comes from the provider project's ancestry and the sweep
    walks folders downward, so a project is only ever planned when it belongs to
    that organization. Only ``ACTIVE`` projects are candidates, and only ones the
    Google provider provisioned (``goog-terraform-provisioned`` label): a project
    created by hand belongs to whoever created it, and prune reports it as
    skipped instead of deleting it. A project the credential cannot delete is
    skipped the same way, so one missing binding never fails the whole sweep.
    """

    project = stack.provider.project
    organization = project_organization(token, project)
    if organization is None:
        return (
            [],
            [f"projects: {project} is not inside an organization; skipping project pruning"],
            [],
        )
    protected = _protected_projects(stack)
    found: list[PrunableResource] = []
    skipped: list[str] = []
    candidates = sorted(
        list_org_projects(token, organization),
        key=lambda item: str(item.get("projectId") or ""),
    )
    for data in candidates:
        project_id = str(data.get("projectId") or "")
        if not project_id:
            continue
        if project_id in protected:
            skipped.append(f"{project_id}: protected project")
            continue
        state = str(data.get("lifecycleState") or "ACTIVE").upper()
        if state != "ACTIVE":
            skipped.append(f"{project_id}: lifecycle state {state}")
            continue
        if not provisioned_by_tofu(data):
            skipped.append(f"{project_id}: not provisioned by OpenTofu (created manually)")
            continue
        if not can_delete_project(token, project_id):
            skipped.append(f"{project_id}: no {PROJECT_DELETE_PERMISSION} permission")
            continue
        found.append(
            PrunableResource(
                section="projects",
                address=f"google_project.project_{slug(project_id)}",
                import_id=project_id,
                block=_prune_project_block(project_id, str(data.get("name") or project_id)),
                description=f"project {project_id}",
            )
        )
    return found, [], skipped


def discover(stack: GcpStack, sections: tuple[str, ...]) -> PrunePlan:
    """Return live resources in ``sections`` that ``stack`` does not declare."""

    if stack.extra_files and not stack.prune.allow_raw_hcl:
        raise PruneError(
            "pruning is disabled for stacks with extra_files: raw HCL resources "
            "are invisible to discovery and would be deleted. Remove them, or set "
            "prune.allow_raw_hcl=True to accept the risk."
        )

    token = access_token(stack)
    resources: list[PrunableResource] = []
    warnings: list[str] = []
    skipped_details: list[str] = []
    if stack.extra_files:
        warnings.append("extra_files are not considered declared: raw HCL resources may be pruned")
    project = stack.provider.project
    protected = _protected_service_accounts(stack)
    other_projects = sorted(
        ({item.project_id for item in stack.projects} | set(stack.external_projects)) - {project}
    )
    if other_projects and "projects" not in sections:
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
    if "project_iam" in sections:
        iam_resources, iam_skipped, iam_details = _project_iam_plan(stack, token, protected)
        resources.extend(iam_resources)
        skipped_details.extend(iam_details)
        reasons = ", ".join(f"{key}={value}" for key, value in iam_skipped.items() if value)
        if reasons:
            warnings.append(f"project_iam: skipped bindings ({reasons})")
    if "service_accounts" in sections:
        resources.extend(_service_account_plan(stack, token, protected))
    if "apis" in sections:
        resources.extend(_api_plan(stack, token))
    if "projects" in sections:
        project_resources, project_warnings, project_details = _project_plan(stack, token)
        resources.extend(project_resources)
        warnings.extend(project_warnings)
        skipped_details.extend(project_details)
    if not resources:
        warnings.append("no undeclared resources found in the selected sections")
    return PrunePlan(
        resources=tuple(resources),
        warnings=tuple(warnings),
        skipped=tuple(skipped_details),
    )


__all__ = [
    "ATTRIBUTION_LABEL",
    "PROJECT_DELETE_PERMISSION",
    "PROTECTED_APIS",
    "PRUNE_SECTIONS",
    "can_delete_project",
    "discover",
    "get_project_iam_bindings",
    "list_buckets",
    "list_folders",
    "list_org_projects",
    "list_projects",
    "list_service_accounts",
    "list_services",
    "list_subscriptions",
    "list_topics",
    "project_organization",
    "provisioned_by_tofu",
]
