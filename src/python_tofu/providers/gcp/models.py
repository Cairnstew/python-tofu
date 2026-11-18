"""Typed GCP resource models.

These models are the authoring layer: write Python, validate it at import time,
then let :class:`python_tofu.providers.gcp.renderer.GcpRenderer` emit OpenTofu
HCL.
"""

from __future__ import annotations

import math
from typing import Literal, Mapping

from pydantic import Field, field_validator, model_validator

from python_tofu.core.hcl import is_reference_template
from python_tofu.core.models import TofuModel
from python_tofu.providers.gcp.quirks import (
    ARTIFACT_REPO_ID_RE,
    BUCKET_NAME_RE,
    CLOUD_FUNCTION_NAME_RE,
    CLOUD_RUN_MEMORY_RE,
    CLOUD_RUN_SERVICE_NAME_RE,
    ENV_VAR_RE,
    FUNCTION_MEMORY_RE,
    PROJECT_ID_RE,
    PUBSUB_NAME_RE,
    SECRET_NAME_RE,
    SERVICE_ACCOUNT_ID_RE,
    TIMEOUT_RE,
    VOLUME_NAME_RE,
    literal_identifier,
    validate_role,
)
from python_tofu.providers.gcp.service_names import DEFAULT_APIS

#: Sections the GCP provider can discover and destroy (in safe deletion order).
GCP_PRUNE_SECTIONS = (
    "buckets",
    "subscriptions",
    "topics",
    "project_iam",
    "service_accounts",
    "apis",
    "projects",
)

StorageClass = Literal[
    "STANDARD",
    "NEARLINE",
    "COLDLINE",
    "ARCHIVE",
    "MULTI_REGIONAL",
    "REGIONAL",
    "DURABLE_REDUCED_AVAILABILITY",
]


class GcpProvider(TofuModel):
    """The ``provider "google"`` block plus provider-level defaults."""

    project: str = Field(min_length=1, description="Default project for resources")
    region: str = "us-central1"
    zone: str | None = None
    credentials: str | None = Field(
        default=None,
        description=(
            "Path to a service-account JSON key (GOOGLE_APPLICATION_CREDENTIALS is preferred)"
        ),
    )
    impersonate_service_account: str | None = None
    default_labels: dict[str, str] = Field(default_factory=dict)
    auto_enable_apis: bool = Field(
        True,
        description=(
            "Enable the APIs declared resources need and order them after the "
            "google_project_service resources. Set false when API enablement is "
            "managed outside this stack."
        ),
    )
    default_apis: tuple[str, ...] = Field(
        default=DEFAULT_APIS,
        description=(
            "Baseline APIs enabled on every owned project and protected from prune. "
            "Defaults to the control-plane set in providers/gcp/service_names.py; "
            "add workload APIs here or in `apis` to keep them, or set () to disable "
            "the baseline. The core control-plane set is never pruned."
        ),
    )

    @field_validator("default_apis")
    @classmethod
    def _default_apis_are_unique_services(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(dict.fromkeys(item.strip() for item in value))
        if any(not item for item in cleaned):
            raise ValueError("default_apis entries must be non-empty service names")
        return cleaned


class GcpProject(TofuModel):
    """A ``google_project`` resource."""

    project_id: str
    name: str
    billing_account: str | None = None
    org_id: str | None = None
    folder_id: str | None = None
    auto_create_network: bool = False
    deletion_policy: Literal["DELETE", "ABANDON"] = "DELETE"
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("project_id")
    @classmethod
    def _valid_project_id(cls, value: str) -> str:
        literal_identifier(
            value,
            "project_id",
            reason="project_id becomes the HCL label and the project cross-reference key.",
        )
        if not PROJECT_ID_RE.match(value):
            raise ValueError(
                "project_id must be 6-30 chars, start with a letter, contain only "
                f"lowercase letters/digits/hyphens and not end with a hyphen: {value!r}"
            )
        return value

    @model_validator(mode="after")
    def _single_parent(self) -> "GcpProject":
        if self.org_id and self.folder_id:
            raise ValueError("a project belongs to either org_id or folder_id, not both")
        return self


class ProjectApi(TofuModel):
    """A ``google_project_service`` resource (API enablement)."""

    project: str
    service: str = Field(min_length=1, description="e.g. compute.googleapis.com")
    disable_on_destroy: bool = False
    disable_dependent_services: bool = Field(
        default=False,
        description=(
            "When disabling, also disable services that depend on this one. "
            "Prune sets this so a dependency chain can be removed in one pass."
        ),
    )


class BillingBudget(TofuModel):
    """A ``google_billing_budget``: an alert-only guardrail on a billing account.

    Budgets never disable billing by themselves; this model only renders
    threshold alerts. The default IAM recipients (billing administrators) get
    the emails unless ``disable_default_recipients`` is set, and extra
    notification channels or a Pub/Sub topic can be attached.
    """

    billing_account: str = Field(description="Billing account id, with or without billingAccounts/")
    display_name: str
    amount: float = Field(gt=0, description="Budget in currency_code units; alert-only")
    currency_code: str = "USD"
    thresholds: tuple[float, ...] = (0.5, 0.9, 1.0)
    spend_basis: Literal["CURRENT_SPEND", "FORECASTED_SPEND"] = "CURRENT_SPEND"
    project_filter: str | None = Field(
        default=None,
        description="Project number (or projects/<number>) to narrow the budget to",
    )
    pubsub_topic: str | None = None
    notification_channels: tuple[str, ...] = ()
    disable_default_recipients: bool = False

    @field_validator("project_filter")
    @classmethod
    def _project_filter_is_a_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        project = value.strip()
        if project.startswith("projects/"):
            project = project.rsplit("/", 1)[-1]
        if not project.isdigit():
            raise ValueError(
                "project_filter must be a project number (or projects/<number>): "
                f"{value!r}. Budget filters do not accept project ids."
            )
        return project

    @field_validator("amount")
    @classmethod
    def _amount_is_usable(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("amount must be a finite number")
        if value < 1e-9:
            raise ValueError("amount must be at least 0.000000001")
        return value

    @field_validator("billing_account")
    @classmethod
    def _account_is_not_empty(cls, value: str) -> str:
        account = value.strip()
        if account.startswith("billingAccounts/"):
            account = account.rsplit("/", 1)[-1]
        if not account:
            raise ValueError("billing_account must not be empty")
        return account

    @model_validator(mode="after")
    def _disabling_defaults_needs_a_target(self) -> "BillingBudget":
        # The provider rejects an ``all_updates_rule`` without one of
        # ``pubsub_topic``/``monitoring_notification_channels``; disabling the
        # default recipients would leave nobody notified anyway.
        if self.disable_default_recipients and not (
            self.pubsub_topic or self.notification_channels
        ):
            raise ValueError(
                "disable_default_recipients requires pubsub_topic or notification_channels"
            )
        return self

    @field_validator("display_name")
    @classmethod
    def _display_name_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("display_name must not be empty")
        return value

    @field_validator("thresholds")
    @classmethod
    def _thresholds_are_percentages(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if not value:
            raise ValueError("thresholds must not be empty")
        invalid = sorted({item for item in value if not 0 < item <= 1})
        if invalid:
            raise ValueError(
                "thresholds are fractions of the budget (0 < t <= 1): "
                + ", ".join(str(item) for item in invalid)
            )
        duplicates = sorted({item for item in value if value.count(item) > 1})
        if duplicates:
            raise ValueError("duplicate thresholds: " + ", ".join(str(item) for item in duplicates))
        return value


class ServiceAccount(TofuModel):
    """A ``google_service_account`` plus optional project IAM role bindings."""

    project: str
    account_id: str
    display_name: str | None = None
    description: str | None = None
    roles: list[str] = Field(default_factory=list)

    @field_validator("account_id")
    @classmethod
    def _valid_account_id(cls, value: str) -> str:
        literal_identifier(
            value,
            "account_id",
            reason="account_id becomes the HCL label and the service-account cross-reference key.",
        )
        if not SERVICE_ACCOUNT_ID_RE.match(value):
            raise ValueError(
                "account_id must be 6-30 chars, start with a letter, contain only "
                f"lowercase letters/digits/hyphens and not end with a hyphen: {value!r}"
            )
        return value

    @field_validator("roles")
    @classmethod
    def _valid_roles(cls, value: list[str]) -> list[str]:
        return [validate_role(item) for item in value]


class StorageBucket(TofuModel):
    """A ``google_storage_bucket`` resource."""

    project: str
    name: str
    location: str = "US"
    storage_class: StorageClass = "STANDARD"
    uniform_bucket_level_access: bool = True
    public_access_prevention: Literal["inherited", "enforced"] = "enforced"
    force_destroy: bool = False
    versioning: bool = False
    labels: dict[str, str] = Field(default_factory=dict)
    estimated_size_gb: float = Field(
        default=0.0,
        ge=0.0,
        description="Estimated stored GB for free-tier checks; never rendered as HCL",
    )

    @field_validator("name")
    @classmethod
    def _valid_bucket_name(cls, value: str) -> str:
        literal_identifier(value, "name", reason="the bucket name becomes the HCL resource label.")
        if not BUCKET_NAME_RE.match(value):
            raise ValueError(
                "bucket names must be 3-63 chars, start/end with a letter or digit, and "
                f"contain only lowercase letters/digits/dots/hyphens/underscores: {value!r}"
            )
        return value


class BucketObject(TofuModel):
    """A ``google_storage_bucket_object``.

    Exactly one content source is required:

    - ``content`` — inline text or raw bytes (bytes are written to the workdir
      and referenced with ``source``, because HCL cannot carry arbitrary bytes);
    - ``source`` — a local file path;
    - ``source_url`` — an HTTP(S) URL fetched by the ``hashicorp/http`` provider
      at plan/apply time.

    Terraform compares the declared content (or file hash) with state, so an
    unchanged object is not re-uploaded. Combine with ``StorageBucket.versioning``
    when previous generations must be retained.
    """

    bucket: str
    name: str
    content: str | bytes | None = None
    source: str | None = None
    source_url: str | None = None
    content_type: str | None = Field(
        default=None,
        description="Defaults to a guess from `name` (e.g. .json → application/json)",
    )
    content_encoding: str | None = None
    content_language: str | None = None
    cache_control: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    storage_class: StorageClass | None = None

    @field_validator("name")
    @classmethod
    def _valid_object_name(cls, value: str) -> str:
        literal_identifier(value, "name", reason="the object name becomes the HCL resource label.")
        if not value or value.startswith("/") or "\n" in value:
            raise ValueError(
                "object names must be a non-empty key without a leading slash or newline: "
                f"{value!r}"
            )
        return value

    @model_validator(mode="after")
    def _one_content_source(self) -> "BucketObject":
        provided = [
            name
            for name, value in (
                ("content", self.content),
                ("source", self.source),
                ("source_url", self.source_url),
            )
            if value is not None
        ]
        if len(provided) != 1:
            raise ValueError(
                "exactly one of content, source or source_url is required; "
                f"got {provided or 'none'}"
            )
        if self.source_url and not self.source_url.startswith(("http://", "https://")):
            raise ValueError(f"source_url must be an http(s) URL: {self.source_url!r}")
        return self


class ProjectIamMember(TofuModel):
    """A standalone ``google_project_iam_member`` binding.

    Set exactly one of:

    - ``member`` — a full principal, e.g. ``user:alice@example.com`` or
      ``serviceAccount:sa@project.iam.gserviceaccount.com``;
    - ``service_account`` — a declared account id or email. It renders as
      ``serviceAccount:${google_service_account.sa_x.email}``, so the binding
      waits for the account and cannot drift from its generated email.
    """

    project: str
    role: str
    member: str | None = Field(
        default=None,
        min_length=3,
        description=(
            "IAM principal, e.g. user:alice@example.com or "
            "serviceAccount:sa@project.iam.gserviceaccount.com"
        ),
    )
    service_account: str | None = Field(
        default=None,
        min_length=1,
        description="Declared account_id or email, rendered as a serviceAccount principal",
    )

    @field_validator("role")
    @classmethod
    def _valid_role(cls, value: str) -> str:
        return validate_role(value)

    @field_validator("service_account")
    @classmethod
    def _service_account_is_id_or_email(cls, value: str | None) -> str | None:
        if value and "/" in value and not is_reference_template(value):
            raise ValueError("service_account must be a declared account_id or email")
        return value

    @model_validator(mode="after")
    def _one_principal(self) -> "ProjectIamMember":
        if bool(self.member) == bool(self.service_account):
            raise ValueError("exactly one of member or service_account is required")
        return self


class ServiceAccountIamMember(TofuModel):
    """A ``google_service_account_iam_member`` binding on the account itself.

    This is the delegation primitive: grant ``roles/iam.serviceAccountUser``
    (actAs) or ``roles/iam.serviceAccountTokenCreator`` (impersonation) to a
    principal on one specific service account. ``service_account`` names the
    target (declared account id or email) and ``member`` is the principal that
    receives the role — with a prefix (``user:``/``group:``/``serviceAccount:``)
    or as a declared account id/email.
    """

    service_account: str = Field(
        min_length=1,
        description="Target account: declared account_id, email or full resource name",
    )
    role: str
    member: str = Field(
        min_length=3,
        description=(
            "IAM principal that receives the role, e.g. user:alice@example.com, "
            "serviceAccount:sa@project.iam.gserviceaccount.com, or a declared account_id"
        ),
    )

    @field_validator("role")
    @classmethod
    def _valid_role(cls, value: str) -> str:
        return validate_role(value)


class SecretEnv(TofuModel):
    """A Secret Manager reference used as an environment variable."""

    secret: str = Field(min_length=1, description="Secret ID or full resource name")
    version: str = Field("latest", min_length=1, description="Secret version, e.g. latest or 7")

    @field_validator("secret")
    @classmethod
    def _valid_secret(cls, value: str) -> str:
        if is_reference_template(value) or value.startswith("projects/"):
            return value
        if not SECRET_NAME_RE.match(value):
            raise ValueError(
                "secret must be a Secret Manager ID or a projects/.../secrets/... resource: "
                f"{value!r}"
            )
        return value


def _env_keys(value: Mapping[str, object], field: str) -> None:
    invalid = sorted(key for key in value if not ENV_VAR_RE.match(key))
    if invalid:
        raise ValueError(f"{field} keys must be valid environment variable names: {invalid}")


class GcsVolume(TofuModel):
    """A Cloud Storage bucket mounted with GCS FUSE (gen2 execution only)."""

    bucket: str = Field(min_length=1)
    read_only: bool = True
    mount_options: list[str] = Field(default_factory=list)

    @field_validator("mount_options")
    @classmethod
    def _no_leading_dashes(cls, value: list[str]) -> list[str]:
        bad = [item for item in value if item.startswith("-")]
        if bad:
            raise ValueError(f"mount_options are passed without leading dashes: {bad}")
        return value


class NfsVolume(TofuModel):
    """An NFS export mounted into the container."""

    server: str = Field(min_length=1)
    path: str = Field(min_length=1)
    read_only: bool = True


class EmptyDirVolume(TofuModel):
    """Ephemeral scratch space shared through the instance."""

    medium: Literal["MEMORY"] = "MEMORY"
    size_limit: str | None = Field(None, description='Quantity, e.g. "512Mi"')


class CloudSqlVolume(TofuModel):
    """Cloud SQL sockets mounted at ``/cloudsql``."""

    instances: list[str] = Field(min_length=1, description="project:region:instance")

    @field_validator("instances")
    @classmethod
    def _no_empty_instances(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("cloud_sql instances must not be empty")
        return value


class SecretVolumeItem(TofuModel):
    """One projected key of a Secret Manager volume."""

    path: str = Field(min_length=1, description="Relative file name in the mount")
    version: str = "latest"
    mode: int | None = Field(None, ge=0, le=0o777)


class SecretVolume(TofuModel):
    """A Secret Manager secret projected into the filesystem."""

    secret: str = Field(min_length=1)
    default_mode: int | None = Field(None, ge=0, le=0o777)
    items: list[SecretVolumeItem] = Field(default_factory=list)

    @field_validator("secret")
    @classmethod
    def _valid_secret(cls, value: str) -> str:
        if is_reference_template(value) or value.startswith("projects/"):
            return value
        if not SECRET_NAME_RE.match(value):
            raise ValueError(
                "secret must be a Secret Manager ID or a projects/.../secrets/... resource: "
                f"{value!r}"
            )
        return value


class Volume(TofuModel):
    """A volume plus the path it is mounted at in the single container.

    Exactly one source (``gcs``/``nfs``/``empty_dir``/``cloud_sql``/``secret``)
    must be set; the renderer emits both the ``volumes`` and ``volume_mounts``
    blocks so the two can never disagree.
    """

    name: str
    mount_path: str = Field(description='Container path, e.g. "/mnt/cache"')
    gcs: GcsVolume | None = None
    nfs: NfsVolume | None = None
    empty_dir: EmptyDirVolume | None = None
    cloud_sql: CloudSqlVolume | None = None
    secret: SecretVolume | None = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not VOLUME_NAME_RE.match(value):
            raise ValueError(
                "volume names must be 1-63 chars, start with a lowercase letter or digit, "
                f"and contain only lowercase letters, digits and hyphens: {value!r}"
            )
        return value

    @model_validator(mode="after")
    def _one_source(self) -> "Volume":
        sources = [
            name
            for name in ("gcs", "nfs", "empty_dir", "cloud_sql", "secret")
            if getattr(self, name) is not None
        ]
        if len(sources) != 1:
            raise ValueError(
                "a volume needs exactly one source "
                f"(gcs/nfs/empty_dir/cloud_sql/secret); got {sources or 'none'}"
            )
        if self.cloud_sql is not None:
            if self.mount_path not in ("", "/cloudsql"):
                raise ValueError('a cloud_sql volume must mount at "/cloudsql" (or "")')
        elif not self.mount_path.startswith("/"):
            raise ValueError(f"mount_path must be absolute: {self.mount_path!r}")
        return self


class HttpProbe(TofuModel):
    """An HTTP health request."""

    path: str = "/"
    port: int | None = Field(None, ge=1, le=65535)
    headers: dict[str, str] = Field(default_factory=dict)


class TcpProbe(TofuModel):
    """A TCP connect health check."""

    port: int | None = Field(None, ge=1, le=65535)


class GrpcProbe(TofuModel):
    """A gRPC health-check request."""

    port: int | None = Field(None, ge=1, le=65535)
    service: str | None = None


class Probe(TofuModel):
    """A startup or liveness probe with exactly one check kind."""

    http_get: HttpProbe | None = None
    tcp_socket: TcpProbe | None = None
    grpc: GrpcProbe | None = None
    initial_delay_seconds: int = Field(0, ge=0)
    timeout_seconds: int = Field(1, ge=1)
    period_seconds: int = Field(10, ge=1)
    failure_threshold: int = Field(3, ge=1)

    @model_validator(mode="after")
    def _one_check(self) -> "Probe":
        kinds = [
            name for name in ("http_get", "tcp_socket", "grpc") if getattr(self, name) is not None
        ]
        if len(kinds) != 1:
            raise ValueError(
                f"a probe needs exactly one of http_get/tcp_socket/grpc; got {kinds or 'none'}"
            )
        if self.timeout_seconds >= self.period_seconds:
            raise ValueError("timeout_seconds must be smaller than period_seconds")
        return self


class CloudRunService(TofuModel):
    """A hardened ``google_cloud_run_v2_service``.

    Defaults are deliberately private and cost-capped: internal-only ingress,
    no unauthenticated invoker, deletion protection on, scale-to-zero with a
    bounded maximum, and 1 vCPU / 512 MiB. Set fields explicitly to opt out.
    """

    project: str
    name: str
    image: str = Field(min_length=1, description="Container image URI or digest")
    location: str | None = Field(None, description="Defaults to the provider region")
    allow_unauthenticated: bool = False
    ingress: Literal["all", "internal", "internal-and-load-balancer"] = "internal"
    deletion_protection: bool = True
    min_instances: int = Field(0, ge=0)
    max_instances: int = Field(10, ge=1)
    cpu: Literal["1", "2", "4", "8"] = "1"
    memory: str = "512Mi"
    concurrency: int | None = Field(None, ge=1, le=1000)
    timeout: str | None = Field(None, description='e.g. "300s"')
    port: int = Field(8080, ge=1, le=65535)
    service_account: str | None = Field(
        None, description="Runtime service-account email or declared account_id"
    )
    env: dict[str, str] = Field(default_factory=dict)
    secret_env: dict[str, SecretEnv] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    vpc_connector: str | None = None
    vpc_egress: Literal["PRIVATE_RANGES_ONLY", "ALL_TRAFFIC"] | None = None
    volumes: list[Volume] = Field(default_factory=list)
    startup_probe: Probe | None = None
    liveness_probe: Probe | None = None
    invoker_service_accounts: list[str] = Field(
        default_factory=list,
        description=(
            "Service accounts granted roles/run.invoker on this service, e.g. a "
            "Pub/Sub push identity"
        ),
    )

    @field_validator("invoker_service_accounts")
    @classmethod
    def _valid_invokers(cls, value: list[str]) -> list[str]:
        for item in value:
            if is_reference_template(item):
                continue
            if "@" not in item and not SERVICE_ACCOUNT_ID_RE.match(item):
                raise ValueError(
                    "invoker_service_accounts entries must be declared account_ids or "
                    f"service-account emails: {item!r}"
                )
        return value

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        literal_identifier(value, "name", reason="the service name becomes the HCL resource label.")
        if not CLOUD_RUN_SERVICE_NAME_RE.match(value):
            raise ValueError(
                "Cloud Run service names must be 1-49 chars, start with a letter, "
                f"and contain only lowercase letters, digits and hyphens: {value!r}"
            )
        return value

    @field_validator("image")
    @classmethod
    def _valid_image(cls, value: str) -> str:
        if not value.strip() or " " in value:
            raise ValueError(f"image must be a container image reference without spaces: {value!r}")
        return value

    @field_validator("memory")
    @classmethod
    def _valid_memory(cls, value: str) -> str:
        if not CLOUD_RUN_MEMORY_RE.match(value):
            raise ValueError(f"Cloud Run memory must look like 512Mi or 1Gi: {value!r}")
        return value

    @field_validator("timeout")
    @classmethod
    def _valid_timeout(cls, value: str | None) -> str | None:
        if value is not None and not TIMEOUT_RE.match(value):
            raise ValueError(f'timeout must look like "300s": {value!r}')
        return value

    @field_validator("env")
    @classmethod
    def _valid_env(cls, value: dict[str, str]) -> dict[str, str]:
        _env_keys(value, "env")
        return value

    @field_validator("secret_env")
    @classmethod
    def _valid_secret_env(cls, value: dict[str, SecretEnv]) -> dict[str, SecretEnv]:
        _env_keys(value, "secret_env")
        return value

    @model_validator(mode="after")
    def _scaling_and_vpc(self) -> "CloudRunService":
        if self.max_instances < self.min_instances:
            raise ValueError("max_instances must be >= min_instances")
        if self.vpc_egress is not None and not self.vpc_connector:
            raise ValueError("vpc_egress requires vpc_connector")
        _validate_volumes(self.volumes)
        if self.startup_probe is not None:
            if self.startup_probe.period_seconds > 240:
                raise ValueError("startup probe period_seconds is limited to 240")
            if self.startup_probe.initial_delay_seconds > 240:
                raise ValueError("startup probe initial_delay_seconds is limited to 240")
        if self.liveness_probe is not None:
            if self.liveness_probe.initial_delay_seconds > 3600:
                raise ValueError("liveness probe initial_delay_seconds is limited to 3600")
        return self


class CloudRunFunction(TofuModel):
    """A hardened 2nd-gen Cloud Run function (``google_cloudfunctions2_function``).

    The source zip is uploaded separately (a ``BucketObject``) and referenced by
    bucket/object name here; the renderer wires the dependency when it finds a
    matching declared object. Defaults are private, scale-to-zero and capped.
    """

    project: str
    name: str
    runtime: str = Field(min_length=1, description="e.g. python312 or nodejs20")
    entry_point: str = Field(min_length=1)
    source_bucket: str = Field(min_length=1)
    source_object: str = Field(min_length=1, description="Zip object name")
    source_generation: str | None = None
    location: str | None = Field(None, description="Defaults to the provider region")
    allow_unauthenticated: bool = False
    ingress: Literal["all", "internal", "internal-and-gclb"] = "internal"
    service_account: str | None = Field(None, description="Runtime service-account email")
    build_service_account: str | None = Field(None, description="Cloud Build service account")
    available_memory: str = "256M"
    available_cpu: str | None = None
    timeout_seconds: int = Field(60, ge=1, le=540)
    min_instances: int = Field(0, ge=0)
    max_instances: int = Field(10, ge=1)
    concurrency: int | None = Field(None, ge=1, le=1000)
    env: dict[str, str] = Field(default_factory=dict)
    secret_env: dict[str, SecretEnv] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        literal_identifier(
            value, "name", reason="the function name becomes the HCL resource label."
        )
        if not CLOUD_FUNCTION_NAME_RE.match(value):
            raise ValueError(
                "function names must be 1-63 chars, start with a letter, and contain "
                f"only lowercase letters, digits and hyphens: {value!r}"
            )
        return value

    @field_validator("available_memory")
    @classmethod
    def _valid_memory(cls, value: str) -> str:
        if not FUNCTION_MEMORY_RE.match(value):
            raise ValueError(f"function memory must look like 256M or 1G: {value!r}")
        return value

    @field_validator("env")
    @classmethod
    def _valid_env(cls, value: dict[str, str]) -> dict[str, str]:
        _env_keys(value, "env")
        return value

    @field_validator("secret_env")
    @classmethod
    def _valid_secret_env(cls, value: dict[str, SecretEnv]) -> dict[str, SecretEnv]:
        _env_keys(value, "secret_env")
        return value

    @model_validator(mode="after")
    def _scaling(self) -> "CloudRunFunction":
        if self.max_instances < self.min_instances:
            raise ValueError("max_instances must be >= min_instances")
        return self


class ArtifactRegistryRepository(TofuModel):
    """A Docker repository for custom container images (``google_artifact_registry_repository``)."""

    project: str
    repository_id: str
    location: str | None = Field(None, description="Defaults to the provider region")
    format: Literal["DOCKER"] = "DOCKER"
    description: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("repository_id")
    @classmethod
    def _valid_repository_id(cls, value: str) -> str:
        literal_identifier(
            value, "repository_id", reason="repository_id becomes the HCL resource label."
        )
        if not ARTIFACT_REPO_ID_RE.match(value):
            raise ValueError(
                "repository_id must be 2-63 chars, start with a letter, and contain "
                f"only lowercase letters, digits, dots, underscores and hyphens: {value!r}"
            )
        return value


def _validate_volumes(volumes: list[Volume]) -> None:
    names = [volume.name for volume in volumes]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"duplicate volume names: {duplicates}")
    paths = [volume.mount_path for volume in volumes if volume.mount_path]
    duplicate_paths = sorted({path for path in paths if paths.count(path) > 1})
    if duplicate_paths:
        raise ValueError(f"duplicate volume mount paths: {duplicate_paths}")


class CloudRunJob(TofuModel):
    """A hardened Cloud Run job (``google_cloud_run_v2_job``).

    Jobs are batch runners: scale to zero, execute a bounded number of tasks and
    exit. Defaults cap retries and CPU/memory and enable deletion protection.
    """

    project: str
    name: str
    image: str = Field(min_length=1)
    location: str | None = Field(None, description="Defaults to the provider region")
    command: list[str] = Field(default_factory=list)
    args: list[str] = Field(default_factory=list)
    service_account: str | None = Field(None, description="Task service-account email")
    cpu: Literal["1", "2", "4", "8"] = "1"
    memory: str = "512Mi"
    task_count: int = Field(1, ge=1)
    parallelism: int = Field(1, ge=1)
    max_retries: int = Field(1, ge=0, le=10)
    timeout: str = Field("600s", description='Per-task timeout, e.g. "600s"')
    deletion_protection: bool = True
    env: dict[str, str] = Field(default_factory=dict)
    secret_env: dict[str, SecretEnv] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        literal_identifier(value, "name", reason="the job name becomes the HCL resource label.")
        if not CLOUD_RUN_SERVICE_NAME_RE.match(value):
            raise ValueError(
                "Cloud Run job names must be 1-49 chars, start with a letter, and "
                f"contain only lowercase letters, digits and hyphens: {value!r}"
            )
        return value

    @field_validator("memory")
    @classmethod
    def _valid_memory(cls, value: str) -> str:
        if not CLOUD_RUN_MEMORY_RE.match(value):
            raise ValueError(f"Cloud Run memory must look like 512Mi or 1Gi: {value!r}")
        return value

    @field_validator("timeout")
    @classmethod
    def _valid_timeout(cls, value: str) -> str:
        if not TIMEOUT_RE.match(value):
            raise ValueError(f'timeout must look like "600s": {value!r}')
        return value

    @field_validator("command", "args")
    @classmethod
    def _no_empty_parts(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("command/args entries must not be empty")
        return value

    @field_validator("env")
    @classmethod
    def _valid_env(cls, value: dict[str, str]) -> dict[str, str]:
        _env_keys(value, "env")
        return value

    @field_validator("secret_env")
    @classmethod
    def _valid_secret_env(cls, value: dict[str, SecretEnv]) -> dict[str, SecretEnv]:
        _env_keys(value, "secret_env")
        return value

    @model_validator(mode="after")
    def _parallelism_fits(self) -> "CloudRunJob":
        if self.parallelism > self.task_count:
            raise ValueError("parallelism must be <= task_count")
        return self


class CloudRunWorkerPool(TofuModel):
    """A hardened Cloud Run worker pool (``google_cloud_run_v2_worker_pool``).

    Worker pools are pull-based background workers: there is no ingress and no
    request traffic, instances start with the container and stay up. Defaults
    are one 1 vCPU / 512 MiB instance, manual scaling and deletion protection.
    """

    project: str
    name: str
    image: str = Field(min_length=1)
    location: str | None = Field(None, description="Defaults to the provider region")
    command: list[str] = Field(default_factory=list)
    args: list[str] = Field(default_factory=list)
    service_account: str | None = Field(None, description="Worker service-account email")
    cpu: Literal["1", "2", "4", "8"] = "1"
    memory: str = "512Mi"
    scaling_mode: Literal["manual", "automatic"] = "manual"
    manual_instance_count: int = Field(1, ge=0, le=1000)
    min_instances: int = Field(0, ge=0)
    max_instances: int = Field(1, ge=1)
    env: dict[str, str] = Field(default_factory=dict)
    secret_env: dict[str, SecretEnv] = Field(default_factory=dict)
    volumes: list[Volume] = Field(default_factory=list)
    vpc_connector: str | None = None
    vpc_egress: Literal["PRIVATE_RANGES_ONLY", "ALL_TRAFFIC"] | None = None
    deletion_protection: bool = True
    launch_stage: Literal["GA", "BETA", "ALPHA"] | None = Field(
        None, description="Set to BETA while worker pools are in preview"
    )
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        literal_identifier(
            value, "name", reason="the worker pool name becomes the HCL resource label."
        )
        if not CLOUD_RUN_SERVICE_NAME_RE.match(value):
            raise ValueError(
                "Cloud Run worker pool names must be 1-49 chars, start with a letter, "
                f"and contain only lowercase letters, digits and hyphens: {value!r}"
            )
        return value

    @field_validator("memory")
    @classmethod
    def _valid_memory(cls, value: str) -> str:
        if not CLOUD_RUN_MEMORY_RE.match(value):
            raise ValueError(f"Cloud Run memory must look like 512Mi or 1Gi: {value!r}")
        return value

    @field_validator("command", "args")
    @classmethod
    def _no_empty_parts(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("command/args entries must not be empty")
        return value

    @field_validator("env")
    @classmethod
    def _valid_env(cls, value: dict[str, str]) -> dict[str, str]:
        _env_keys(value, "env")
        return value

    @field_validator("secret_env")
    @classmethod
    def _valid_secret_env(cls, value: dict[str, SecretEnv]) -> dict[str, SecretEnv]:
        _env_keys(value, "secret_env")
        return value

    @model_validator(mode="after")
    def _scaling_and_vpc(self) -> "CloudRunWorkerPool":
        if self.scaling_mode == "automatic" and self.max_instances < self.min_instances:
            raise ValueError("max_instances must be >= min_instances")
        if self.vpc_egress is not None and not self.vpc_connector:
            raise ValueError("vpc_egress requires vpc_connector")
        _validate_volumes(self.volumes)
        return self


def _duration_seconds(value: str) -> float:
    return float(value[:-1])


class PubSubTopic(TofuModel):
    """A Pub/Sub topic (``google_pubsub_topic``)."""

    project: str
    name: str
    message_retention_duration: str | None = Field(
        default=None,
        description='Topic retention, e.g. "600s"; 10 minutes to 31 days',
    )
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        literal_identifier(value, "name", reason="the topic name becomes the HCL resource label.")
        if not PUBSUB_NAME_RE.match(value):
            raise ValueError(
                "Pub/Sub names must be 3-255 chars, start with a letter, and contain "
                f"only letters, digits, dashes, underscores, periods, tildes, + or %: {value!r}"
            )
        return value

    @field_validator("message_retention_duration")
    @classmethod
    def _valid_retention(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not TIMEOUT_RE.match(value):
            raise ValueError(f'message_retention_duration must look like "600s": {value!r}')
        seconds = _duration_seconds(value)
        if not 600 <= seconds <= 2_678_400:
            raise ValueError("topic retention must be between 10 minutes and 31 days")
        return value


class DeadLetter(TofuModel):
    """Dead-letter settings for a subscription."""

    topic: str = Field(min_length=3, description="Declared topic name or full resource path")
    max_delivery_attempts: int = Field(default=5, ge=5, le=100)

    @field_validator("topic")
    @classmethod
    def _valid_topic(cls, value: str) -> str:
        if is_reference_template(value):
            return value
        name = value.rsplit("/", 1)[-1]
        if not PUBSUB_NAME_RE.match(name):
            raise ValueError(f"dead-letter topic must be a Pub/Sub name or path: {value!r}")
        return value


class RetryPolicy(TofuModel):
    """Exponential backoff between delivery attempts."""

    minimum_backoff: str = Field(default="10s", description='e.g. "10s"')
    maximum_backoff: str = Field(default="600s", description='e.g. "600s"')

    @field_validator("minimum_backoff", "maximum_backoff")
    @classmethod
    def _valid_backoff(cls, value: str) -> str:
        if not TIMEOUT_RE.match(value):
            raise ValueError(f'backoff must look like "10s": {value!r}')
        if _duration_seconds(value) > 600:
            raise ValueError("backoff cannot exceed 600s")
        return value

    @model_validator(mode="after")
    def _ordered(self) -> "RetryPolicy":
        if _duration_seconds(self.minimum_backoff) > _duration_seconds(self.maximum_backoff):
            raise ValueError("minimum_backoff must be <= maximum_backoff")
        return self


class PubSubSubscription(TofuModel):
    """A pull or push subscription (``google_pubsub_subscription``).

    ``push_service`` points at a declared :class:`CloudRunService` and resolves
    to its ``uri``; the service must grant ``roles/run.invoker`` to
    ``push_service_account`` for the push to be accepted.
    """

    project: str
    name: str
    topic: str = Field(min_length=3, description="Declared topic name or full resource path")
    ack_deadline_seconds: int = Field(default=10, ge=10, le=600)
    message_retention_duration: str | None = Field(
        default=None, description='e.g. "604800s" (7 days)'
    )
    retain_acked_messages: bool = False
    expiration_ttl: str = Field(
        default="2678400s",
        description=(
            'Idle expiry, minimum "86400s". The provider silently drops "", so an '
            'explicit duration is required; "315360000s" approximates "never".'
        ),
    )
    filter: str | None = Field(
        default=None, description="Attribute filter, max 256 bytes; immutable"
    )
    dead_letter: DeadLetter | None = None
    retry: RetryPolicy | None = None
    enable_message_ordering: bool = False
    enable_exactly_once_delivery: bool = False
    push_endpoint: str | None = Field(
        default=None, description="Explicit push URL for external webhooks"
    )
    push_service: str | None = Field(
        default=None, description="Declared Cloud Run service to push to"
    )
    push_service_account: str | None = Field(
        default=None, description="OIDC identity, declared account_id or email"
    )
    push_audience: str | None = Field(
        default=None, description="OIDC audience; defaults to the endpoint"
    )
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        literal_identifier(
            value, "name", reason="the subscription name becomes the HCL resource label."
        )
        if not PUBSUB_NAME_RE.match(value):
            raise ValueError(
                "Pub/Sub names must be 3-255 chars, start with a letter, and contain "
                f"only letters, digits, dashes, underscores, periods, tildes, + or %: {value!r}"
            )
        return value

    @field_validator("topic")
    @classmethod
    def _valid_topic(cls, value: str) -> str:
        if is_reference_template(value):
            return value
        name = value.rsplit("/", 1)[-1]
        if not PUBSUB_NAME_RE.match(name):
            raise ValueError(f"topic must be a Pub/Sub name or path: {value!r}")
        return value

    @field_validator("filter")
    @classmethod
    def _valid_filter(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("filter must not be blank")
        if len(value.encode()) > 256:
            raise ValueError("filter is limited to 256 bytes")
        return value

    @field_validator("message_retention_duration")
    @classmethod
    def _valid_retention(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not TIMEOUT_RE.match(value):
            raise ValueError(f'message_retention_duration must look like "604800s": {value!r}')
        seconds = _duration_seconds(value)
        if not 600 <= seconds <= 604_800:
            raise ValueError("subscription retention must be between 10 minutes and 7 days")
        return value

    @field_validator("expiration_ttl")
    @classmethod
    def _valid_expiry(cls, value: str) -> str:
        if not TIMEOUT_RE.match(value):
            raise ValueError(f'expiration_ttl must look like "2678400s" (never ""): {value!r}')
        if _duration_seconds(value) < 86_400:
            raise ValueError("expiration_ttl must be at least 86400s (1 day)")
        return value

    @field_validator("push_endpoint")
    @classmethod
    def _valid_endpoint(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError(f"push_endpoint must be an http(s) URL: {value!r}")
        return value

    @field_validator("push_service_account")
    @classmethod
    def _valid_push_account(cls, value: str | None) -> str | None:
        if value is None or is_reference_template(value):
            return value
        if "@" not in value and not SERVICE_ACCOUNT_ID_RE.match(value):
            raise ValueError(
                "push_service_account must be a declared account_id or a service-account "
                f"email: {value!r}"
            )
        return value

    @model_validator(mode="after")
    def _push_and_dead_letter(self) -> "PubSubSubscription":
        if self.push_endpoint and self.push_service:
            raise ValueError("set either push_endpoint or push_service, not both")
        if self.push_service_account and not (self.push_endpoint or self.push_service):
            raise ValueError("push_service_account requires push_endpoint or push_service")
        if self.push_audience and not self.push_service_account:
            raise ValueError("push_audience requires push_service_account")
        if self.enable_exactly_once_delivery and (self.push_endpoint or self.push_service):
            raise ValueError("exactly-once delivery is supported for pull subscriptions only")
        if self.dead_letter is not None:
            own = self.topic.rsplit("/", 1)[-1]
            if self.dead_letter.topic.rsplit("/", 1)[-1] == own:
                raise ValueError("dead_letter.topic must differ from the subscription topic")
        return self


class GcpBackendConfig(TofuModel):
    """OpenTofu state backend for the Google provider.

    ``prefix`` defaults to ``python-tofu/<stack name>`` so two stacks sharing a
    state bucket never share an object prefix. Set it explicitly to override.
    """

    kind: Literal["local", "gcs"] = "gcs"
    bucket: str | None = None
    prefix: str | None = None
    path: str | None = None

    @model_validator(mode="after")
    def _required_fields(self) -> "GcpBackendConfig":
        if self.kind == "gcs" and not self.bucket:
            raise ValueError("a gcs backend requires `bucket`")
        if self.kind == "local" and not self.path:
            raise ValueError("a local backend requires `path`")
        return self

    def prefix_for(self, stack_name: str | None) -> str | None:
        """Return the GCS object prefix, defaulting to ``python-tofu/<name>``."""

        if self.kind != "gcs":
            return None
        return self.prefix or f"python-tofu/{stack_name or 'state'}"


# Public compatibility alias: the top-level package exposes ``BackendConfig``.
BackendConfig = GcpBackendConfig

__all__ = [
    "ArtifactRegistryRepository",
    "BackendConfig",
    "BillingBudget",
    "CloudRunFunction",
    "CloudRunJob",
    "CloudRunService",
    "CloudRunWorkerPool",
    "GCP_PRUNE_SECTIONS",
    "BucketObject",
    "GcpBackendConfig",
    "GcpProject",
    "GcpProvider",
    "DeadLetter",
    "ProjectApi",
    "ProjectIamMember",
    "PubSubSubscription",
    "PubSubTopic",
    "RetryPolicy",
    "CloudSqlVolume",
    "EmptyDirVolume",
    "GcsVolume",
    "GrpcProbe",
    "HttpProbe",
    "NfsVolume",
    "Probe",
    "SecretEnv",
    "SecretVolume",
    "SecretVolumeItem",
    "ServiceAccount",
    "ServiceAccountIamMember",
    "StorageBucket",
    "StorageClass",
    "TcpProbe",
    "TofuModel",
    "Volume",
]
