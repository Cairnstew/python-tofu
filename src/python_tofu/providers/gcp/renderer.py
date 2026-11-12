"""Render a :class:`~python_tofu.providers.gcp.stack.GcpStack` to OpenTofu HCL.

GCP-specific shapes live here: ``google_*`` resource blocks, the ``google``
provider block, the GCS/local backend, and the service-account/role email
interpolation. The file contract and ``terraform`` scaffolding are inherited
from :class:`python_tofu.core.renderer.BaseRenderer`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from python_tofu.core.hcl import Attr, Block, Raw, attr, body
from python_tofu.core.renderer import BaseRenderer
from python_tofu.core.results import RenderResult
from python_tofu.providers.gcp.models import (
    BucketObject,
    GcpProject,
    ProjectApi,
    ProjectIamMember,
    ServiceAccount,
    StorageBucket,
)
from python_tofu.providers.gcp.quirks import guess_content_type, require_unique, slug
from python_tofu.providers.gcp.stack import GcpStack


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
            backend_body = body(attr("bucket", backend.bucket), attr("prefix", backend.prefix))
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

        for api in stack.apis:
            address = f"google_project_service.api_{slug(api.service)}"
            require_unique(seen, address, f"api {api.service!r}")
            blocks.append(_api_block(api))

        for account in stack.service_accounts:
            address = f"google_service_account.sa_{slug(account.account_id)}"
            require_unique(seen, address, f"service account {account.account_id!r}")
            blocks.append(_service_account_block(account))
            for role_block in _service_account_role_blocks(account):
                role_address = ".".join((role_block.kind, *role_block.labels))
                require_unique(
                    seen,
                    role_address,
                    f"role binding for service account {account.account_id!r}",
                )
                blocks.append(role_block)

        for bucket in stack.buckets:
            address = f"google_storage_bucket.bucket_{slug(bucket.name)}"
            require_unique(seen, address, f"bucket {bucket.name!r}")
            blocks.append(_bucket_block(bucket))

        for item in stack.bucket_objects:
            address = f"google_storage_bucket_object.object_{slug(item.name)}"
            require_unique(seen, address, f"object {item.name!r} in {item.bucket!r}")
            blocks.append(self._bucket_object_block(item, stack))

        for binding in stack.iam_members:
            address = f"google_project_iam_member.iam_{slug(binding.role)}_{slug(binding.member)}"
            require_unique(seen, address, f"IAM binding {binding.role!r} for {binding.member!r}")
            blocks.append(_iam_member_block(binding))

        return blocks

    # ── bucket objects ────────────────────────────────────────────────
    def data_blocks(self, stack: GcpStack) -> list[Block]:
        seen: dict[str, str] = {}
        blocks: list[Block] = []
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
