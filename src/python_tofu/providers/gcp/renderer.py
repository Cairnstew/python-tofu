"""Render a :class:`~python_tofu.providers.gcp.stack.GcpStack` to OpenTofu HCL.

GCP-specific shapes live here: ``google_*`` resource blocks, the ``google``
provider block, the GCS/local backend, and the service-account/role email
interpolation. The file contract and ``terraform`` scaffolding are inherited
from :class:`python_tofu.core.renderer.BaseRenderer`.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

from python_tofu.core.exceptions import RenderError
from python_tofu.core.hcl import Attr, Block, Raw, attr, body
from python_tofu.core.renderer import BaseRenderer
from python_tofu.core.results import RenderResult
from python_tofu.providers.gcp.apis import apis_for, declared_apis
from python_tofu.providers.gcp.models import (
    ArtifactRegistryRepository,
    BillingBudget,
    BucketObject,
    CloudRunFunction,
    CloudRunJob,
    CloudRunService,
    CloudRunWorkerPool,
    GcpProject,
    Probe,
    ProjectApi,
    ProjectIamMember,
    PubSubSubscription,
    PubSubTopic,
    SecretEnv,
    ServiceAccount,
    StorageBucket,
    Volume,
)
from python_tofu.providers.gcp.quirks import guess_content_type, require_unique, slug
from python_tofu.providers.gcp.stack import GcpStack


def _with_api_deps(block: Block, stack: "GcpStack", project: str, resource: object) -> Block:
    """Order a resource after the API enablement it depends on.

    ``google_project_service`` resources are siblings, not parents, in the
    dependency graph, so a first apply into a fresh project can otherwise race
    and fail with a 403 for a disabled API.
    """

    emitted = {(api.project, api.service) for api in declared_apis(stack)}
    refs = tuple(
        Raw(f"google_project_service.api_{slug(service)}")
        for service in apis_for(stack, resource)
        if (project, service) in emitted
    )
    if not refs:
        return block
    return Block(block.kind, block.labels, body(*block.body, Attr("depends_on", refs)))


def _object_project(stack: "GcpStack", item: BucketObject) -> str:
    for bucket in stack.buckets:
        if bucket.name == item.bucket:
            return bucket.project
    return stack.provider.project


def _project_block(project: GcpProject) -> Block:
    return Block(
        "resource",
        ("google_project", f"project_{slug(project.project_id)}"),
        body(
            Attr("project_id", project.project_id),
            Attr("name", project.name),
            attr("billing_account", project.billing_account),
            attr("org_id", project.org_id),
            attr("folder_id", project.folder_id),
            Attr("auto_create_network", project.auto_create_network),
            Attr("deletion_policy", project.deletion_policy),
            attr("labels", project.labels or None),
        ),
    )


def _billing_budget_block(budget: BillingBudget) -> Block:
    """Render ``google_billing_budget`` as an alert-only guardrail."""

    amount = Decimal(str(budget.amount))
    units = int(amount)
    nanos = int((amount - units) * Decimal(1_000_000_000))
    if units == 0 and nanos == 0:  # sub-nano amounts round up to the smallest unit
        nanos = 1

    filter_attrs = []
    if budget.project_filter:
        project = budget.project_filter
        if not project.startswith("projects/"):
            project = f"projects/{project}"
        filter_attrs.append(Attr("projects", [project]))

    return Block(
        "resource",
        ("google_billing_budget", f"budget_{slug(budget.display_name)}"),
        body(
            Attr("billing_account", budget.billing_account),
            Attr("display_name", budget.display_name),
            Block(
                "amount",
                body=body(
                    Block(
                        "specified_amount",
                        body=body(
                            Attr("currency_code", budget.currency_code),
                            Attr("units", str(units)),
                            attr("nanos", nanos or None),
                        ),
                    )
                ),
            ),
            Block("budget_filter", body=body(*filter_attrs)) if filter_attrs else None,
            *(
                Block(
                    "threshold_rules",
                    body=body(
                        Attr("threshold_percent", threshold),
                        Attr("spend_basis", budget.spend_basis),
                    ),
                )
                for threshold in budget.thresholds
            ),
            Block(
                "all_updates_rule",
                body=body(
                    attr("pubsub_topic", budget.pubsub_topic),
                    attr(
                        "monitoring_notification_channels",
                        list(budget.notification_channels) or None,
                    ),
                    Attr("disable_default_iam_recipients", budget.disable_default_recipients),
                ),
            ),
        ),
    )


def _api_block(api: ProjectApi) -> Block:
    return Block(
        "resource",
        ("google_project_service", f"api_{slug(api.service)}"),
        body(
            Attr("project", api.project),
            Attr("service", api.service),
            Attr("disable_on_destroy", api.disable_on_destroy),
        ),
    )


def _service_account_block(account: ServiceAccount) -> Block:
    return Block(
        "resource",
        ("google_service_account", f"sa_{slug(account.account_id)}"),
        body(
            Attr("project", account.project),
            Attr("account_id", account.account_id),
            attr("display_name", account.display_name),
            attr("description", account.description),
        ),
    )


def _service_account_role_blocks(account: ServiceAccount) -> list[Block]:
    sa_local = f"sa_{slug(account.account_id)}"
    member = f"serviceAccount:${{google_service_account.{sa_local}.email}}"
    blocks: list[Block] = []
    for role in sorted(account.roles):
        blocks.append(
            Block(
                "resource",
                ("google_project_iam_member", f"iam_{sa_local}_{slug(role)}"),
                body(
                    Attr("project", account.project),
                    Attr("role", role),
                    Attr("member", member),
                ),
            )
        )
    return blocks


def _bucket_block(bucket: StorageBucket) -> Block:
    versioning = Block("versioning", body=(Attr("enabled", True),)) if bucket.versioning else None
    return Block(
        "resource",
        ("google_storage_bucket", f"bucket_{slug(bucket.name)}"),
        body(
            Attr("project", bucket.project),
            Attr("name", bucket.name),
            Attr("location", bucket.location),
            Attr("storage_class", bucket.storage_class),
            Attr("uniform_bucket_level_access", bucket.uniform_bucket_level_access),
            Attr("public_access_prevention", bucket.public_access_prevention),
            Attr("force_destroy", bucket.force_destroy),
            attr("labels", bucket.labels or None),
            versioning,
        ),
    )


def _iam_member_block(binding: ProjectIamMember) -> Block:
    return Block(
        "resource",
        (
            "google_project_iam_member",
            f"iam_{slug(binding.role)}_{slug(binding.member)}",
        ),
        body(
            Attr("project", binding.project),
            Attr("role", binding.role),
            Attr("member", binding.member),
        ),
    )


_INGRESS = {
    "all": "INGRESS_TRAFFIC_ALL",
    "internal": "INGRESS_TRAFFIC_INTERNAL_ONLY",
    "internal-and-load-balancer": "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER",
}
_FUNCTION_INGRESS = {
    "all": "ALLOW_ALL",
    "internal": "ALLOW_INTERNAL_ONLY",
    "internal-and-gclb": "ALLOW_INTERNAL_AND_GCLB",
}


def _secret_key_ref(secret: SecretEnv) -> Block:
    return Block(
        "value_source",
        body=body(
            Block(
                "secret_key_ref",
                body=body(Attr("secret", secret.secret), Attr("version", secret.version)),
            )
        ),
    )


def _env_blocks(env: dict[str, str], secret_env: dict[str, SecretEnv]) -> list[Block]:
    blocks = [
        Block("env", body=body(Attr("name", name), Attr("value", value)))
        for name, value in sorted(env.items())
    ]
    blocks.extend(
        Block("env", body=body(Attr("name", name), _secret_key_ref(secret)))
        for name, secret in sorted(secret_env.items())
    )
    return blocks


def _service_account_value(stack: "GcpStack", value: str | None) -> str | Raw | None:
    """Reference a declared service account so ordering is implicit."""

    if value is None:
        return None
    for account in stack.service_accounts:
        email = f"{account.account_id}@{account.project}.iam.gserviceaccount.com"
        if value in (account.account_id, email):
            return Raw(f"google_service_account.sa_{slug(account.account_id)}.email")
    return value


def _volume_source(volume: Volume) -> Block:
    if volume.gcs is not None:
        return Block(
            "gcs",
            body=body(
                Attr("bucket", volume.gcs.bucket),
                Attr("read_only", volume.gcs.read_only),
                attr("mount_options", volume.gcs.mount_options or None),
            ),
        )
    if volume.nfs is not None:
        return Block(
            "nfs",
            body=body(
                Attr("server", volume.nfs.server),
                Attr("path", volume.nfs.path),
                Attr("read_only", volume.nfs.read_only),
            ),
        )
    if volume.empty_dir is not None:
        return Block(
            "empty_dir",
            body=body(
                Attr("medium", volume.empty_dir.medium),
                attr("size_limit", volume.empty_dir.size_limit),
            ),
        )
    if volume.cloud_sql is not None:
        return Block(
            "cloud_sql_instance",
            body=body(Attr("instances", volume.cloud_sql.instances)),
        )
    if volume.secret is None:  # the model guarantees exactly one variant
        raise RenderError("volume declares no variant")
    return Block(
        "secret",
        body=body(
            Attr("secret", volume.secret.secret),
            attr("default_mode", volume.secret.default_mode),
            *[
                Block(
                    "items",
                    body=body(
                        Attr("path", item.path),
                        Attr("version", item.version),
                        attr("mode", item.mode),
                    ),
                )
                for item in volume.secret.items
            ],
        ),
    )


def _volume_blocks(volumes: list[Volume]) -> list[Block]:
    return [
        Block("volumes", body=body(Attr("name", volume.name), _volume_source(volume)))
        for volume in volumes
    ]


def _volume_mount_blocks(volumes: list[Volume]) -> list[Block]:
    return [
        Block(
            "volume_mounts",
            body=body(Attr("name", volume.name), Attr("mount_path", volume.mount_path)),
        )
        for volume in volumes
        if volume.mount_path
    ]


def _probe_block(probe: Probe, name: str) -> Block:
    if probe.http_get is not None:
        check = Block(
            "http_get",
            body=body(
                Attr("path", probe.http_get.path),
                attr("port", probe.http_get.port),
                *[
                    Block(
                        "http_headers",
                        body=body(Attr("name", key), Attr("value", value)),
                    )
                    for key, value in sorted(probe.http_get.headers.items())
                ],
            ),
        )
    elif probe.tcp_socket is not None:
        check = Block("tcp_socket", body=body(attr("port", probe.tcp_socket.port)))
    else:
        if probe.grpc is None:  # the model guarantees exactly one variant
            raise RenderError("probe declares no variant")
        check = Block(
            "grpc",
            body=body(
                attr("port", probe.grpc.port),
                attr("service", probe.grpc.service),
            ),
        )
    return Block(
        name,
        body=body(
            attr("initial_delay_seconds", probe.initial_delay_seconds),
            attr("timeout_seconds", probe.timeout_seconds),
            attr("period_seconds", probe.period_seconds),
            attr("failure_threshold", probe.failure_threshold),
            check,
        ),
    )


def _scaling_block(
    mode: str, manual_instance_count: int, min_instances: int, max_instances: int
) -> Block:
    if mode == "manual":
        return Block(
            "scaling",
            body=body(
                Attr("scaling_mode", "MANUAL"),
                Attr("manual_instance_count", manual_instance_count),
            ),
        )
    return Block(
        "scaling",
        body=body(
            Attr("scaling_mode", "AUTOMATIC"),
            Attr("min_instance_count", min_instances),
            Attr("max_instance_count", max_instances),
        ),
    )


def _worker_pool_block(pool: CloudRunWorkerPool, stack: "GcpStack") -> Block:
    location = pool.location or stack.provider.region
    container = body(
        Attr("image", pool.image),
        attr("command", pool.command or None),
        attr("args", pool.args or None),
        Block(
            "resources",
            body=body(Attr("limits", {"cpu": pool.cpu, "memory": pool.memory})),
        ),
        *_volume_mount_blocks(pool.volumes),
        *_env_blocks(pool.env, pool.secret_env),
    )
    template = body(
        attr("service_account", _service_account_value(stack, pool.service_account)),
        (
            Block(
                "vpc_access",
                body=body(
                    Attr("connector", pool.vpc_connector),
                    attr("egress", pool.vpc_egress),
                ),
            )
            if pool.vpc_connector
            else None
        ),
        Block("containers", body=container),
        *_volume_blocks(pool.volumes),
    )
    return Block(
        "resource",
        ("google_cloud_run_v2_worker_pool", f"pool_{slug(pool.name)}"),
        body(
            Attr("project", pool.project),
            Attr("name", pool.name),
            Attr("location", location),
            Attr("deletion_protection", pool.deletion_protection),
            attr("launch_stage", pool.launch_stage),
            attr("labels", pool.labels or None),
            Block("template", body=template),
            _scaling_block(
                pool.scaling_mode,
                pool.manual_instance_count,
                pool.min_instances,
                pool.max_instances,
            ),
        ),
    )


def _topic_ref(stack: "GcpStack", value: str, project: str) -> str | Raw:
    """Resolve a declared topic to its resource, otherwise build a full path."""

    name = value.rsplit("/", 1)[-1]
    prefix = f"projects/{project}/"
    if value.startswith("projects/") and not value.startswith(prefix):
        return value
    if any(topic.name == name for topic in stack.pubsub_topics):
        return Raw(f"google_pubsub_topic.topic_{slug(name)}.id")
    if value.startswith("projects/"):
        return value
    return f"{prefix}topics/{name}"


def _iam_member_value(stack: "GcpStack", value: str) -> str | Raw:
    for account in stack.service_accounts:
        email = f"{account.account_id}@{account.project}.iam.gserviceaccount.com"
        if value in (account.account_id, email):
            return Raw(
                f'"serviceAccount:${{google_service_account.sa_{slug(account.account_id)}.email}}"'
            )
    return f"serviceAccount:{value}"


def _pubsub_topic_block(topic: PubSubTopic) -> Block:
    return Block(
        "resource",
        ("google_pubsub_topic", f"topic_{slug(topic.name)}"),
        body(
            Attr("project", topic.project),
            Attr("name", topic.name),
            attr("message_retention_duration", topic.message_retention_duration),
            attr("labels", topic.labels or None),
        ),
    )


def _pubsub_subscription_block(subscription: PubSubSubscription, stack: "GcpStack") -> Block:
    push = None
    if subscription.push_endpoint or subscription.push_service:
        if subscription.push_service:
            endpoint: str | Raw = Raw(
                f"google_cloud_run_v2_service.run_{slug(subscription.push_service)}.uri"
            )
        else:
            endpoint = str(subscription.push_endpoint)
        oidc = None
        if subscription.push_service_account:
            oidc = Block(
                "oidc_token",
                body=body(
                    Attr(
                        "service_account_email",
                        _service_account_value(stack, subscription.push_service_account),
                    ),
                    attr("audience", subscription.push_audience),
                ),
            )
        push = Block(
            "push_config",
            body=body(Attr("push_endpoint", endpoint), oidc),
        )

    dead_letter = None
    if subscription.dead_letter is not None:
        dead_letter = Block(
            "dead_letter_policy",
            body=body(
                Attr(
                    "dead_letter_topic",
                    _topic_ref(stack, subscription.dead_letter.topic, subscription.project),
                ),
                Attr(
                    "max_delivery_attempts",
                    subscription.dead_letter.max_delivery_attempts,
                ),
            ),
        )

    retry = None
    if subscription.retry is not None:
        retry = Block(
            "retry_policy",
            body=body(
                Attr("minimum_backoff", subscription.retry.minimum_backoff),
                Attr("maximum_backoff", subscription.retry.maximum_backoff),
            ),
        )

    return Block(
        "resource",
        ("google_pubsub_subscription", f"sub_{slug(subscription.name)}"),
        body(
            Attr("project", subscription.project),
            Attr("name", subscription.name),
            Attr("topic", _topic_ref(stack, subscription.topic, subscription.project)),
            Attr("ack_deadline_seconds", subscription.ack_deadline_seconds),
            attr("message_retention_duration", subscription.message_retention_duration),
            (Attr("retain_acked_messages", True) if subscription.retain_acked_messages else None),
            Block(
                "expiration_policy",
                body=body(Attr("ttl", subscription.expiration_ttl)),
            ),
            attr("filter", subscription.filter),
            dead_letter,
            retry,
            (
                Attr("enable_message_ordering", True)
                if subscription.enable_message_ordering
                else None
            ),
            (
                Attr("enable_exactly_once_delivery", True)
                if subscription.enable_exactly_once_delivery
                else None
            ),
            push,
            attr("labels", subscription.labels or None),
        ),
    )


def _dead_letter_iam_block(subscription: PubSubSubscription, stack: "GcpStack") -> Block:
    if subscription.dead_letter is None:  # only called for subscriptions that set one
        raise RenderError("dead-letter helper called without a dead_letter")
    topic = subscription.dead_letter.topic.rsplit("/", 1)[-1]
    topic_value: str | Raw = (
        Raw(f"google_pubsub_topic.topic_{slug(topic)}.name")
        if any(declared.name == topic for declared in stack.pubsub_topics)
        else topic
    )
    project = subscription.project
    member = (
        '"serviceAccount:service-'
        f"${{data.google_project.project_{slug(project)}.number}}"
        '@gcp-sa-pubsub.iam.gserviceaccount.com"'
    )
    return Block(
        "resource",
        (
            "google_pubsub_topic_iam_member",
            f"dlq_publisher_{slug(project)}_{slug(topic)}",
        ),
        body(
            Attr("project", project),
            Attr("topic", topic_value),
            Attr("role", "roles/pubsub.publisher"),
            Attr("member", Raw(member)),
        ),
    )


def _service_account_name_ref(stack: "GcpStack", value: str) -> str | Raw:
    """Full ``projects/.../serviceAccounts/...`` name for an IAM member target."""

    for account in stack.service_accounts:
        email = f"{account.account_id}@{account.project}.iam.gserviceaccount.com"
        if value in (account.account_id, email):
            return Raw(f"google_service_account.sa_{slug(account.account_id)}.name")
    _, _, domain = value.partition("@")
    suffix = ".iam.gserviceaccount.com"
    project = domain.removesuffix(suffix) if domain.endswith(suffix) else stack.provider.project
    return f"projects/{project}/serviceAccounts/{value}"


def _push_token_creator_block(subscription: PubSubSubscription, stack: "GcpStack") -> Block:
    """Let the Pub/Sub service agent mint OIDC tokens for the push identity."""

    if subscription.push_service_account is None:  # only called when one is set
        raise RenderError("push helper called without a push_service_account")
    member = (
        '"serviceAccount:service-'
        f"${{data.google_project.project_{slug(subscription.project)}.number}}"
        '@gcp-sa-pubsub.iam.gserviceaccount.com"'
    )
    return Block(
        "resource",
        (
            "google_service_account_iam_member",
            f"pubsub_token_creator_{slug(subscription.name)}",
        ),
        body(
            Attr(
                "service_account_id",
                _service_account_name_ref(stack, subscription.push_service_account),
            ),
            Attr("role", "roles/iam.serviceAccountTokenCreator"),
            Attr("member", Raw(member)),
        ),
    )


def _service_invoker_block(service: "CloudRunService", account: str, stack: "GcpStack") -> Block:
    location = service.location or stack.provider.region
    return Block(
        "resource",
        (
            "google_cloud_run_v2_service_iam_member",
            f"run_invoker_{slug(service.name)}_{slug(account)}",
        ),
        body(
            Attr("project", service.project),
            Attr("location", location),
            Attr(
                "name",
                Raw(f"google_cloud_run_v2_service.run_{slug(service.name)}.name"),
            ),
            Attr("role", "roles/run.invoker"),
            Attr("member", _iam_member_value(stack, account)),
        ),
    )


def _cloud_run_service_block(service: CloudRunService, stack: "GcpStack") -> Block:
    location = service.location or stack.provider.region
    container = body(
        Attr("image", service.image),
        Block(
            "resources",
            body=body(Attr("limits", {"cpu": service.cpu, "memory": service.memory})),
        ),
        Block("ports", body=body(Attr("container_port", service.port))),
        *_volume_mount_blocks(service.volumes),
        *_env_blocks(service.env, service.secret_env),
        (
            _probe_block(service.startup_probe, "startup_probe")
            if service.startup_probe is not None
            else None
        ),
        (
            _probe_block(service.liveness_probe, "liveness_probe")
            if service.liveness_probe is not None
            else None
        ),
    )
    template = body(
        attr("service_account", _service_account_value(stack, service.service_account)),
        attr("timeout", service.timeout),
        attr("max_instance_request_concurrency", service.concurrency),
        Block(
            "scaling",
            body=body(
                Attr("min_instance_count", service.min_instances),
                Attr("max_instance_count", service.max_instances),
            ),
        ),
        Block("containers", body=container),
        *_volume_blocks(service.volumes),
        (
            Block(
                "vpc_access",
                body=body(
                    Attr("connector", service.vpc_connector),
                    attr("egress", service.vpc_egress),
                ),
            )
            if service.vpc_connector
            else None
        ),
    )
    return Block(
        "resource",
        ("google_cloud_run_v2_service", f"run_{slug(service.name)}"),
        body(
            Attr("project", service.project),
            Attr("name", service.name),
            Attr("location", location),
            Attr("ingress", _INGRESS[service.ingress]),
            Attr("deletion_protection", service.deletion_protection),
            attr("labels", service.labels or None),
            Block("template", body=template),
        ),
    )


def _cloud_run_service_iam_block(service: CloudRunService, stack: "GcpStack") -> Block:
    location = service.location or stack.provider.region
    return Block(
        "resource",
        ("google_cloud_run_v2_service_iam_member", f"run_invoker_{slug(service.name)}"),
        body(
            Attr("project", service.project),
            Attr("location", location),
            Attr(
                "name",
                Raw(f"google_cloud_run_v2_service.run_{slug(service.name)}.name"),
            ),
            Attr("role", "roles/run.invoker"),
            Attr("member", "allUsers"),
        ),
    )


def _function_source(
    function: CloudRunFunction, stack: "GcpStack"
) -> tuple[str | Raw, str | Raw, str | Raw | None]:
    """Reference a declared source zip so the function waits for the upload."""

    item = next(
        (
            candidate
            for candidate in stack.bucket_objects
            if candidate.bucket == function.source_bucket
            and candidate.name == function.source_object
        ),
        None,
    )
    if item is None:
        return (
            function.source_bucket,
            function.source_object,
            function.source_generation,
        )
    local = f"object_{slug(item.name)}"
    return (
        Raw(f"google_storage_bucket_object.{local}.bucket"),
        Raw(f"google_storage_bucket_object.{local}.name"),
        function.source_generation or Raw(f"google_storage_bucket_object.{local}.generation"),
    )


def _cloud_run_function_block(function: CloudRunFunction, stack: "GcpStack") -> Block:
    location = function.location or stack.provider.region
    bucket, obj, generation = _function_source(function, stack)
    build = body(
        Attr("runtime", function.runtime),
        Attr("entry_point", function.entry_point),
        attr(
            "service_account",
            _service_account_value(stack, function.build_service_account),
        ),
        Block(
            "source",
            body=body(
                Block(
                    "storage_source",
                    body=body(
                        Attr("bucket", bucket),
                        Attr("object", obj),
                        attr("generation", generation),
                    ),
                )
            ),
        ),
    )
    service_config = body(
        attr(
            "service_account_email",
            _service_account_value(stack, function.service_account),
        ),
        Attr("available_memory", function.available_memory),
        attr("available_cpu", function.available_cpu),
        Attr("timeout_seconds", function.timeout_seconds),
        Attr("max_instance_count", function.max_instances),
        Attr("min_instance_count", function.min_instances),
        attr("max_instance_request_concurrency", function.concurrency),
        Attr("ingress_settings", _FUNCTION_INGRESS[function.ingress]),
        attr("environment_variables", function.env or None),
        *[
            Block(
                "secret_environment_variables",
                body=body(
                    Attr("key", key),
                    Attr("project_id", function.project),
                    Attr("secret", secret.secret),
                    Attr("version", secret.version),
                ),
            )
            for key, secret in sorted(function.secret_env.items())
        ],
    )
    return Block(
        "resource",
        ("google_cloudfunctions2_function", f"fn_{slug(function.name)}"),
        body(
            Attr("project", function.project),
            Attr("name", function.name),
            Attr("location", location),
            attr("labels", function.labels or None),
            Block("build_config", body=build),
            Block("service_config", body=service_config),
        ),
    )


def _cloud_run_function_iam_block(function: CloudRunFunction, stack: "GcpStack") -> Block:
    location = function.location or stack.provider.region
    return Block(
        "resource",
        (
            "google_cloudfunctions2_function_iam_member",
            f"function_invoker_{slug(function.name)}",
        ),
        body(
            Attr("project", function.project),
            Attr("location", location),
            Attr(
                "cloud_function",
                Raw(f"google_cloudfunctions2_function.fn_{slug(function.name)}.name"),
            ),
            Attr("role", "roles/cloudfunctions.invoker"),
            Attr("member", "allUsers"),
        ),
    )


def _artifact_registry_repository_block(
    repository: ArtifactRegistryRepository, stack: "GcpStack"
) -> Block:
    location = repository.location or stack.provider.region
    return Block(
        "resource",
        (
            "google_artifact_registry_repository",
            f"repo_{slug(repository.repository_id)}",
        ),
        body(
            Attr("project", repository.project),
            Attr("location", location),
            Attr("repository_id", repository.repository_id),
            Attr("format", repository.format),
            attr("description", repository.description),
            attr("labels", repository.labels or None),
        ),
    )


def _cloud_run_job_block(job: CloudRunJob, stack: "GcpStack") -> Block:
    location = job.location or stack.provider.region
    container = body(
        Attr("image", job.image),
        attr("command", job.command or None),
        attr("args", job.args or None),
        Block(
            "resources",
            body=body(Attr("limits", {"cpu": job.cpu, "memory": job.memory})),
        ),
        *_env_blocks(job.env, job.secret_env),
    )
    execution = body(
        attr("service_account", _service_account_value(stack, job.service_account)),
        Attr("timeout", job.timeout),
        Attr("max_retries", job.max_retries),
        Block("containers", body=container),
    )
    return Block(
        "resource",
        ("google_cloud_run_v2_job", f"job_{slug(job.name)}"),
        body(
            Attr("project", job.project),
            Attr("name", job.name),
            Attr("location", location),
            Attr("deletion_protection", job.deletion_protection),
            attr("labels", job.labels or None),
            Block(
                "template",
                body=body(
                    Attr("task_count", job.task_count),
                    Attr("parallelism", job.parallelism),
                    Block("template", body=execution),
                ),
            ),
        ),
    )


class GcpRenderer(BaseRenderer[GcpStack]):
    """Write ``versions.tf``, ``providers.tf``, ``main.tf`` and ``.gitignore``."""

    OBJECT_DIR = ".objects"
    GITIGNORE = BaseRenderer.GITIGNORE + ".objects/\n"

    def required_providers(self, stack: GcpStack) -> dict[str, dict[str, str]]:
        providers = {
            "google": {"source": "hashicorp/google", "version": stack.google_provider_version}
        }
        if any(item.source_url for item in stack.bucket_objects):
            providers["http"] = {"source": "hashicorp/http", "version": "~> 3.4"}
        return providers

    def backend_block(self, stack: GcpStack) -> Block | None:
        backend = stack.backend
        if backend is None:
            return None
        if backend.kind == "gcs":
            prefix = backend.prefix_for(stack.name)
            backend_body = body(attr("bucket", backend.bucket), Attr("prefix", prefix))
        else:
            backend_body = body(attr("path", backend.path))
        return Block("backend", (backend.kind,), backend_body)

    def provider_blocks(self, stack: GcpStack) -> list[Block]:
        provider = stack.provider
        return [
            Block(
                "provider",
                ("google",),
                body(
                    Attr("project", provider.project),
                    Attr("region", provider.region),
                    attr("zone", provider.zone),
                    attr("credentials", provider.credentials),
                    attr("impersonate_service_account", provider.impersonate_service_account),
                    attr("default_labels", provider.default_labels or None),
                ),
            )
        ]

    def resource_blocks(self, stack: GcpStack) -> list[Block]:
        """Build the resource blocks in a stable, readable order."""

        seen: dict[str, str] = {}
        blocks: list[Block] = []

        for project in stack.projects:
            address = f"google_project.project_{slug(project.project_id)}"
            require_unique(seen, address, f"project {project.project_id!r}")
            blocks.append(_project_block(project))

        for budget in stack.billing_budgets:
            address = f"google_billing_budget.budget_{slug(budget.display_name)}"
            require_unique(seen, address, f"billing budget {budget.display_name!r}")
            blocks.append(_billing_budget_block(budget))

        for api in declared_apis(stack):
            address = f"google_project_service.api_{slug(api.service)}"
            require_unique(seen, address, f"api {api.service!r}")
            blocks.append(_api_block(api))

        for account in stack.service_accounts:
            address = f"google_service_account.sa_{slug(account.account_id)}"
            require_unique(seen, address, f"service account {account.account_id!r}")
            blocks.append(
                _with_api_deps(_service_account_block(account), stack, account.project, account)
            )
            for role_block in _service_account_role_blocks(account):
                role_address = ".".join((role_block.kind, *role_block.labels))
                require_unique(
                    seen,
                    role_address,
                    f"role binding for service account {account.account_id!r}",
                )
                blocks.append(_with_api_deps(role_block, stack, account.project, account))

        for bucket in stack.buckets:
            address = f"google_storage_bucket.bucket_{slug(bucket.name)}"
            require_unique(seen, address, f"bucket {bucket.name!r}")
            blocks.append(_with_api_deps(_bucket_block(bucket), stack, bucket.project, bucket))

        for item in stack.bucket_objects:
            address = f"google_storage_bucket_object.object_{slug(item.name)}"
            require_unique(seen, address, f"object {item.name!r} in {item.bucket!r}")
            blocks.append(
                _with_api_deps(
                    self._bucket_object_block(item, stack),
                    stack,
                    _object_project(stack, item),
                    item,
                )
            )

        for binding in stack.iam_members:
            address = f"google_project_iam_member.iam_{slug(binding.role)}_{slug(binding.member)}"
            require_unique(seen, address, f"IAM binding {binding.role!r} for {binding.member!r}")
            blocks.append(
                _with_api_deps(_iam_member_block(binding), stack, binding.project, binding)
            )

        for repository in stack.artifact_registry_repositories:
            address = f"google_artifact_registry_repository.repo_{slug(repository.repository_id)}"
            require_unique(seen, address, f"Artifact Registry repo {repository.repository_id!r}")
            blocks.append(
                _with_api_deps(
                    _artifact_registry_repository_block(repository, stack),
                    stack,
                    repository.project,
                    repository,
                )
            )

        for service in stack.cloud_run_services:
            address = f"google_cloud_run_v2_service.run_{slug(service.name)}"
            require_unique(seen, address, f"Cloud Run service {service.name!r}")
            blocks.append(
                _with_api_deps(
                    _cloud_run_service_block(service, stack), stack, service.project, service
                )
            )
            if service.allow_unauthenticated:
                invoker = f"google_cloud_run_v2_service_iam_member.run_invoker_{slug(service.name)}"
                require_unique(seen, invoker, f"public invoker for {service.name!r}")
                blocks.append(
                    _with_api_deps(
                        _cloud_run_service_iam_block(service, stack),
                        stack,
                        service.project,
                        service,
                    )
                )
            for invoker_account in service.invoker_service_accounts:
                invoker = (
                    "google_cloud_run_v2_service_iam_member."
                    f"run_invoker_{slug(service.name)}_{slug(invoker_account)}"
                )
                require_unique(seen, invoker, f"invoker {invoker_account!r} for {service.name!r}")
                blocks.append(
                    _with_api_deps(
                        _service_invoker_block(service, invoker_account, stack),
                        stack,
                        service.project,
                        service,
                    )
                )

        for declared_topic in stack.pubsub_topics:
            address = f"google_pubsub_topic.topic_{slug(declared_topic.name)}"
            require_unique(seen, address, f"Pub/Sub topic {declared_topic.name!r}")
            blocks.append(
                _with_api_deps(
                    _pubsub_topic_block(declared_topic),
                    stack,
                    declared_topic.project,
                    declared_topic,
                )
            )

        dead_letter_iam: set[tuple[str, str]] = set()
        for subscription in stack.pubsub_subscriptions:
            address = f"google_pubsub_subscription.sub_{slug(subscription.name)}"
            require_unique(seen, address, f"Pub/Sub subscription {subscription.name!r}")
            blocks.append(
                _with_api_deps(
                    _pubsub_subscription_block(subscription, stack),
                    stack,
                    subscription.project,
                    subscription,
                )
            )
            if subscription.dead_letter is not None:
                dlq = subscription.dead_letter.topic.rsplit("/", 1)[-1]
                key = (subscription.project, dlq)
                if key not in dead_letter_iam:
                    dead_letter_iam.add(key)
                    iam_address = (
                        "google_pubsub_topic_iam_member."
                        f"dlq_publisher_{slug(subscription.project)}_{slug(dlq)}"
                    )
                    require_unique(seen, iam_address, f"dead-letter publisher grant for {dlq!r}")
                    blocks.append(
                        _with_api_deps(
                            _dead_letter_iam_block(subscription, stack),
                            stack,
                            subscription.project,
                            subscription,
                        )
                    )
            if subscription.push_service_account is not None:
                token_address = (
                    "google_service_account_iam_member."
                    f"pubsub_token_creator_{slug(subscription.name)}"
                )
                require_unique(
                    seen,
                    token_address,
                    f"push token creator for {subscription.name!r}",
                )
                blocks.append(
                    _with_api_deps(
                        _push_token_creator_block(subscription, stack),
                        stack,
                        subscription.project,
                        subscription,
                    )
                )

        for pool in stack.cloud_run_worker_pools:
            address = f"google_cloud_run_v2_worker_pool.pool_{slug(pool.name)}"
            require_unique(seen, address, f"Cloud Run worker pool {pool.name!r}")
            blocks.append(
                _with_api_deps(_worker_pool_block(pool, stack), stack, pool.project, pool)
            )

        for job in stack.cloud_run_jobs:
            address = f"google_cloud_run_v2_job.job_{slug(job.name)}"
            require_unique(seen, address, f"Cloud Run job {job.name!r}")
            blocks.append(_with_api_deps(_cloud_run_job_block(job, stack), stack, job.project, job))

        for function in stack.cloud_run_functions:
            address = f"google_cloudfunctions2_function.fn_{slug(function.name)}"
            require_unique(seen, address, f"Cloud Run function {function.name!r}")
            blocks.append(
                _with_api_deps(
                    _cloud_run_function_block(function, stack), stack, function.project, function
                )
            )
            if function.allow_unauthenticated:
                invoker = (
                    "google_cloudfunctions2_function_iam_member."
                    f"function_invoker_{slug(function.name)}"
                )
                require_unique(seen, invoker, f"public invoker for {function.name!r}")
                blocks.append(
                    _with_api_deps(
                        _cloud_run_function_iam_block(function, stack),
                        stack,
                        function.project,
                        function,
                    )
                )

        return blocks

    # ── bucket objects ────────────────────────────────────────────────
    def data_blocks(self, stack: GcpStack) -> list[Block]:
        seen: dict[str, str] = {}
        blocks: list[Block] = []

        data_projects = sorted(
            {
                subscription.project
                for subscription in stack.pubsub_subscriptions
                if subscription.dead_letter is not None
                or subscription.push_service_account is not None
            }
        )
        for dead_letter_project in data_projects:
            blocks.append(
                Block(
                    "data",
                    ("google_project", f"project_{slug(dead_letter_project)}"),
                    body(Attr("project_id", dead_letter_project)),
                )
            )
        for item in stack.bucket_objects:
            if item.source_url:
                address = f"data.http.object_{slug(item.name)}"
                require_unique(seen, address, f"URL source for object {item.name!r}")
                blocks.append(self._http_data_block(item))
        return blocks

    def _binary_path(self, item: BucketObject) -> Path:
        """Deterministic path for bytes that HCL cannot carry inline."""

        payload = item.content if isinstance(item.content, bytes) else b""
        digest = hashlib.sha256(payload).hexdigest()[:16]
        return self.workdir / self.OBJECT_DIR / f"{digest}.bin"

    def _object_content(self, item: BucketObject) -> Attr:
        if isinstance(item.content, bytes):
            return Attr("source", str(self._binary_path(item)))
        if item.content is not None:
            return Attr("content", item.content)
        if item.source is not None:
            return Attr("source", str(Path(item.source).expanduser().resolve()))
        # Validation guarantees a URL here; the data block is emitted first.
        return Attr("content", Raw(f"data.http.object_{slug(item.name)}.response_body"))

    def _http_data_block(self, item: BucketObject) -> Block:
        return Block(
            "data",
            ("http", f"object_{slug(item.name)}"),
            body(Attr("url", item.source_url)),
        )

    def _bucket_reference(self, bucket: str, stack: GcpStack) -> Attr:
        """Reference a declared bucket so objects wait for it; literals for external ones."""

        for declared in stack.buckets:
            if declared.name == bucket:
                return Attr(
                    "bucket",
                    Raw(f"google_storage_bucket.bucket_{slug(declared.name)}.name"),
                )
        return Attr("bucket", bucket)

    def _bucket_object_block(self, item: BucketObject, stack: GcpStack) -> Block:
        return Block(
            "resource",
            ("google_storage_bucket_object", f"object_{slug(item.name)}"),
            body(
                self._bucket_reference(item.bucket, stack),
                Attr("name", item.name),
                self._object_content(item),
                Attr("content_type", item.content_type or guess_content_type(item.name)),
                attr("cache_control", item.cache_control),
                attr("content_encoding", item.content_encoding),
                attr("content_language", item.content_language),
                attr("metadata", item.metadata or None),
                attr("storage_class", item.storage_class),
            ),
        )

    def render(self, stack: GcpStack) -> RenderResult:
        """Materialise inline bytes before writing the HCL that references them."""

        for item in stack.bucket_objects:
            if isinstance(item.content, bytes):
                path = self._binary_path(item)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(item.content)
        return super().render(stack)
