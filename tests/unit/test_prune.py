from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from python_tofu.core.exceptions import PruneError
from python_tofu.core.models import PruneConfig
from python_tofu.providers.gcp import GCP, GcpProvider, GcpStack
from python_tofu.providers.gcp import prune as gcp_prune
from python_tofu.providers.gcp.models import (
    GCP_PRUNE_SECTIONS,
    GcpProject,
    ProjectApi,
    ProjectIamMember,
    ServiceAccount,
    StorageBucket,
)
from python_tofu.providers.gcp.prune import discover
from python_tofu.providers.gcp.renderer import GcpRenderer
from python_tofu.core.prune import Reaper

BUCKETS = [
    {"name": "//storage.googleapis.com/projects/_/buckets/declared-bucket", "location": "EU"},
    {
        "name": "//storage.googleapis.com/projects/_/buckets/stray-bucket",
        "location": "US-CENTRAL1",
        "storageClass": "NEARLINE",
        "versioning": {"enabled": True},
        "iamConfiguration": {
            "uniformBucketLevelAccess": {"enabled": True},
            "publicAccessPrevention": "enforced",
        },
    },
    {"name": "//storage.googleapis.com/projects/_/buckets/external-bucket", "location": "US"},
]

SERVICE_ACCOUNTS = [
    {"email": "ci-runner@demo-project.iam.gserviceaccount.com"},
    {"email": "manual@demo-project.iam.gserviceaccount.com", "displayName": "Manual"},
    {"email": "123456789-compute@developer.gserviceaccount.com"},
    {"email": "demo-project@appspot.gserviceaccount.com"},
    {"email": "service-123@gcp-sa-pubsub.iam.gserviceaccount.com"},
]

APIS = [
    {"name": "projects/123/services/storage.googleapis.com", "state": "ENABLED"},
    {"name": "projects/123/services/pubsub.googleapis.com", "state": "ENABLED"},
    {"name": "projects/123/services/cloudasset.googleapis.com", "state": "ENABLED"},
    {"name": "projects/123/services/cloudbilling.googleapis.com", "state": "ENABLED"},
    {"name": "projects/123/services/bigquery.googleapis.com", "state": "DISABLED"},
]

IAM_POLICY = [
    {
        "role": "roles/storage.objectViewer",
        "members": ["serviceAccount:ci-runner@demo-project.iam.gserviceaccount.com"],
    },
    {
        "role": "roles/viewer",
        "members": [
            "serviceAccount:ci-runner@demo-project.iam.gserviceaccount.com",
            "user:alice@example.com",
            "group:devs@example.com",
            "domain:example.com",
            "allUsers",
            "allAuthenticatedUsers",
        ],
    },
    {
        "role": "roles/owner",
        "members": ["serviceAccount:ci-runner@demo-project.iam.gserviceaccount.com"],
    },
    {
        "role": "roles/editor",
        "members": ["serviceAccount:ci-runner@demo-project.iam.gserviceaccount.com"],
        "condition": {"title": "temporary"},
    },
    {
        "role": "roles/viewer",
        "members": ["serviceAccount:manual@demo-project.iam.gserviceaccount.com"],
    },
]


def _stack(**overrides: object) -> GcpStack:
    values: dict[str, object] = {
        "provider": GcpProvider(project="demo-project"),
        "buckets": [
            StorageBucket(project="demo-project", name="declared-bucket"),
            StorageBucket(project="demo-project", name="declared-bucket-two"),
        ],
        "service_accounts": [
            ServiceAccount(project="demo-project", account_id="ci-runner"),
        ],
        "apis": [ProjectApi(project="demo-project", service="storage.googleapis.com")],
        "external_buckets": ["external-bucket"],
    }
    values.update(overrides)
    return GcpStack(**values)  # type: ignore[arg-type]


@pytest.fixture
def inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gcp_prune, "access_token", lambda stack: "token")
    monkeypatch.setattr(gcp_prune, "list_buckets", lambda project, token: BUCKETS)
    monkeypatch.setattr(gcp_prune, "list_service_accounts", lambda project, token: SERVICE_ACCOUNTS)
    monkeypatch.setattr(gcp_prune, "list_services", lambda project, token: APIS)
    monkeypatch.setattr(gcp_prune, "list_topics", lambda project, token: [])
    monkeypatch.setattr(gcp_prune, "list_subscriptions", lambda project, token: [])
    monkeypatch.setattr(gcp_prune, "get_project_iam_bindings", lambda project, token: [])
    monkeypatch.setattr(gcp_prune, "credential_identities", lambda *args, **kwargs: frozenset())


# ── config ────────────────────────────────────────────────────────────
def test_prune_is_off_by_default() -> None:
    assert _stack().prune.enabled is False
    assert _stack().prune.resolve(GCP_PRUNE_SECTIONS, ("project_iam",)) == tuple(
        section for section in GCP_PRUNE_SECTIONS if section != "project_iam"
    )


def test_project_iam_is_explicit_only() -> None:
    explicit_only = ("project_iam", "projects")
    implicit = PruneConfig(enabled=True).resolve(GCP_PRUNE_SECTIONS, explicit_only)
    explicit = PruneConfig(enabled=True, sections=("project_iam",)).resolve(
        GCP_PRUNE_SECTIONS, explicit_only
    )

    assert "project_iam" not in implicit
    assert explicit == ("project_iam",)
    assert GCP.prune_explicit_only == explicit_only


def test_roles_owner_is_always_a_protected_iam_role() -> None:
    assert PruneConfig().protected_iam_roles == ("roles/owner",)
    assert PruneConfig(protected_iam_roles=()).protected_iam_roles == ("roles/owner",)
    assert PruneConfig(protected_iam_roles=("roles/editor",)).protected_iam_roles == (
        "roles/owner",
        "roles/editor",
    )


def test_prune_sections_resolve_in_provider_order() -> None:
    config = PruneConfig(enabled=True, sections=("apis", "buckets"))
    assert config.resolve(GCP_PRUNE_SECTIONS) == ("buckets", "apis")


def test_prune_rejects_unknown_sections() -> None:
    config = PruneConfig(enabled=True, sections=("nope",))
    with pytest.raises(ValueError, match="unsupported prune section"):
        config.resolve(GCP_PRUNE_SECTIONS)


def test_stack_rejects_unknown_prune_section() -> None:
    with pytest.raises(ValidationError, match="unsupported prune section"):
        _stack(prune=PruneConfig(enabled=True, sections=("nope",)))


def test_all_cannot_be_mixed_with_other_sections() -> None:
    with pytest.raises(ValidationError, match="cannot be combined"):
        PruneConfig(sections=("all", "buckets"))


def test_prune_with_extra_files_requires_opt_in() -> None:
    raw = {"raw.tf": 'resource "google_storage_bucket" "raw" { name = "raw" }'}
    with pytest.raises(ValidationError, match="extra_files"):
        _stack(prune=PruneConfig(enabled=True), extra_files=raw)


def test_discover_refuses_extra_files_without_opt_in() -> None:
    raw = {"raw.tf": 'resource "google_storage_bucket" "raw" { name = "raw" }'}
    with pytest.raises(PruneError, match="extra_files"):
        discover(_stack(extra_files=raw), ("buckets",))


def test_allow_raw_hcl_warns_on_discovery(inventory: None) -> None:
    raw = {"raw.tf": 'resource "google_storage_bucket" "raw" { name = "raw" }'}
    stack = _stack(
        extra_files=raw,
        prune=PruneConfig(enabled=True, allow_raw_hcl=True),
    )
    plan = discover(stack, ("buckets",))
    assert any("extra_files" in warning for warning in plan.warnings)


# ── discovery ─────────────────────────────────────────────────────────
def test_discovery_prunes_only_undeclared_resources(inventory: None) -> None:
    # ``projects`` is explicit-only, so a resolved "all" never includes it; this
    # test covers the per-project sections.
    sections = tuple(section for section in GCP_PRUNE_SECTIONS if section != "projects")
    plan = discover(_stack(prune=PruneConfig(enabled=True)), sections)

    descriptions = [resource.description for resource in plan.resources]
    assert descriptions == [
        "bucket stray-bucket",
        "service account manual@demo-project.iam.gserviceaccount.com",
        "API pubsub.googleapis.com",
    ]


def test_active_identity_is_never_pruned(inventory: None, monkeypatch: pytest.MonkeyPatch) -> None:
    admin = "org-admin@demo-project.iam.gserviceaccount.com"
    monkeypatch.setattr(
        gcp_prune, "credential_identities", lambda *args, **kwargs: frozenset({admin})
    )
    monkeypatch.setattr(
        gcp_prune,
        "list_service_accounts",
        lambda project, token: [
            {"email": admin},
            {"email": "manual@demo-project.iam.gserviceaccount.com"},
        ],
    )

    plan = discover(_stack(), ("service_accounts",))

    assert [resource.description for resource in plan.resources] == [
        "service account manual@demo-project.iam.gserviceaccount.com"
    ]


def test_protected_service_accounts_accept_ids_and_emails(
    inventory: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = _stack(
        prune=PruneConfig(
            enabled=True,
            protected_service_accounts=("manual", "other@demo-project.iam.gserviceaccount.com"),
        )
    )
    monkeypatch.setattr(
        gcp_prune,
        "list_service_accounts",
        lambda project, token: [
            {"email": "manual@demo-project.iam.gserviceaccount.com"},
            {"email": "other@demo-project.iam.gserviceaccount.com"},
            {"email": "stray-account@demo-project.iam.gserviceaccount.com"},
        ],
    )

    plan = discover(stack, ("service_accounts",))

    assert [resource.description for resource in plan.resources] == [
        "service account stray-account@demo-project.iam.gserviceaccount.com"
    ]


def test_discovery_import_ids_and_addresses(inventory: None) -> None:
    plan = discover(_stack(), ("buckets",))

    (bucket,) = plan.resources
    assert bucket.address == "google_storage_bucket.bucket_stray_bucket"
    assert bucket.import_id == "demo-project/stray-bucket"
    assert "force_destroy" in _render_block(bucket)


def test_discovery_skips_protected_apis_inventory(inventory: None) -> None:
    plan = discover(_stack(), ("apis",))

    services = {resource.description for resource in plan.resources}
    assert "API pubsub.googleapis.com" in services
    assert "API cloudasset.googleapis.com" not in services
    assert "API cloudbilling.googleapis.com" not in services
    assert "API storage.googleapis.com" not in services
    assert "API bigquery.googleapis.com" not in services


def _iam_stack(**overrides: object) -> GcpStack:
    values: dict[str, object] = {
        "service_accounts": [
            ServiceAccount(
                project="demo-project",
                account_id="ci-runner",
                roles=["roles/storage.objectViewer"],
            )
        ],
    }
    values.update(overrides)
    return _stack(**values)


def test_project_iam_prunes_only_managed_undeclared_bindings(
    inventory: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gcp_prune, "get_project_iam_bindings", lambda project, token: IAM_POLICY)

    plan = discover(_iam_stack(), ("project_iam",))

    assert [resource.description for resource in plan.resources] == [
        "IAM binding roles/viewer for serviceAccount:ci-runner@demo-project.iam.gserviceaccount.com"
    ]
    assert any("project_iam: skipped bindings" in warning for warning in plan.warnings)


def test_project_iam_import_id_and_address(
    inventory: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gcp_prune, "get_project_iam_bindings", lambda project, token: IAM_POLICY)

    (binding,) = discover(_iam_stack(), ("project_iam",)).resources

    assert binding.import_id == (
        "demo-project roles/viewer serviceAccount:ci-runner@demo-project.iam.gserviceaccount.com"
    )
    assert binding.address.startswith("google_project_iam_member.prune_iam_roles_viewer_")


def test_project_iam_treats_a_declared_service_account_binding_as_declared(
    inventory: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        gcp_prune,
        "get_project_iam_bindings",
        lambda project, token: [
            {
                "role": "roles/viewer",
                "members": ["serviceAccount:ci-runner@demo-project.iam.gserviceaccount.com"],
            }
        ],
    )
    stack = _iam_stack(
        iam_members=[
            ProjectIamMember(
                project="demo-project",
                role="roles/viewer",
                service_account="ci-runner",
            )
        ]
    )

    assert discover(stack, ("project_iam",)).resources == ()


def test_project_iam_never_prunes_the_active_identity(
    inventory: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = "org-admin@demo-project.iam.gserviceaccount.com"
    monkeypatch.setattr(
        gcp_prune, "credential_identities", lambda *args, **kwargs: frozenset({admin})
    )
    monkeypatch.setattr(
        gcp_prune,
        "get_project_iam_bindings",
        lambda project, token: [{"role": "roles/viewer", "members": [f"serviceAccount:{admin}"]}],
    )
    stack = _iam_stack(
        service_accounts=[
            ServiceAccount(
                project="demo-project",
                account_id="ci-runner",
                roles=["roles/storage.objectViewer"],
            ),
            ServiceAccount(project="demo-project", account_id="org-admin"),
        ]
    )

    assert discover(stack, ("project_iam",)).resources == ()


def test_project_iam_skips_conditional_and_owner_bindings(
    inventory: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        gcp_prune,
        "get_project_iam_bindings",
        lambda project, token: [
            {
                "role": "roles/viewer",
                "members": ["serviceAccount:ci-runner@demo-project.iam.gserviceaccount.com"],
                "condition": {"title": "temporary"},
            },
            {
                "role": "roles/owner",
                "members": ["serviceAccount:ci-runner@demo-project.iam.gserviceaccount.com"],
            },
        ],
    )

    plan = discover(_iam_stack(), ("project_iam",))

    assert plan.resources == ()
    assert any("conditional=" in warning for warning in plan.warnings)
    assert any("protected-role=" in warning for warning in plan.warnings)


def test_roles_editor_is_not_protected_by_default(
    inventory: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        gcp_prune,
        "get_project_iam_bindings",
        lambda project, token: [
            {
                "role": "roles/editor",
                "members": ["serviceAccount:ci-runner@demo-project.iam.gserviceaccount.com"],
            }
        ],
    )

    assert len(discover(_iam_stack(), ("project_iam",)).resources) == 1


def test_configurable_protected_iam_roles(inventory: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gcp_prune,
        "get_project_iam_bindings",
        lambda project, token: [
            {
                "role": "roles/editor",
                "members": ["serviceAccount:ci-runner@demo-project.iam.gserviceaccount.com"],
            }
        ],
    )
    stack = _iam_stack(prune=PruneConfig(enabled=True, protected_iam_roles=("roles/editor",)))

    plan = discover(stack, ("project_iam",))

    assert plan.resources == ()
    assert any("protected-role=1" in warning for warning in plan.warnings)


def test_explain_style_details_cover_each_skip_reason(
    inventory: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gcp_prune, "get_project_iam_bindings", lambda project, token: IAM_POLICY)

    plan = discover(_iam_stack(), ("project_iam",))

    assert any(
        "user:alice@example.com roles/viewer (non-service-account)" in item for item in plan.skipped
    )
    assert any("roles/owner (protected-role)" in item for item in plan.skipped)
    assert any("roles/editor (conditional)" in item for item in plan.skipped)
    assert any(
        "manual@demo-project.iam.gserviceaccount.com roles/viewer (not-declared)" in item
        for item in plan.skipped
    )


def test_get_project_iam_bindings_requests_policy_version_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(url: str, token: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((url, payload))
        return {"bindings": [{"role": "roles/viewer", "members": ["user:a@example.com"]}]}

    monkeypatch.setattr(gcp_prune, "post_json", fake_post)
    bindings = gcp_prune.get_project_iam_bindings("demo-project", "token")

    assert bindings == [{"role": "roles/viewer", "members": ["user:a@example.com"]}]
    assert calls[0][0].endswith("/projects/demo-project:getIamPolicy")
    assert calls[0][1] == {"options": {"requestedPolicyVersion": 3}}


def test_bucket_listing_follows_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_get(url: str, token: str, params: dict[str, str]) -> dict[str, object]:
        calls.append((url, dict(params)))
        if len(calls) == 1:
            return {"items": [{"name": "a"}], "nextPageToken": "next"}
        return {"items": [{"name": "b"}]}

    monkeypatch.setattr(gcp_prune, "get_json", fake_get)

    assert gcp_prune.list_buckets("demo-project", "token") == [{"name": "a"}, {"name": "b"}]
    assert calls[0][0] == "https://storage.googleapis.com/storage/v1/b"
    assert calls[0][1] == {"project": "demo-project"}
    assert calls[1][1]["pageToken"] == "next"


def test_discovery_warns_about_other_projects(inventory: None) -> None:
    stack = _stack(projects=[GcpProject(project_id="other-project", name="Other")])

    plan = discover(stack, ("buckets",))

    assert any("only inspects demo-project" in item for item in plan.warnings)


def test_discovery_section_selection(inventory: None) -> None:
    plan = discover(_stack(), ("service_accounts",))

    assert [resource.section for resource in plan.resources] == ["service_accounts"]


# ── reaper ────────────────────────────────────────────────────────────
def _render_block(resource: object) -> str:
    from python_tofu.core.hcl import render

    return render(resource.block)  # type: ignore[attr-defined]


def test_reaper_config_has_no_backend(inventory: None) -> None:
    stack = _stack()
    plan = discover(stack, ("buckets",))
    text = Reaper("/tmp/does-not-exist", GcpRenderer("/tmp/does-not-exist"), stack).config_text(
        plan.resources
    )

    assert "backend" not in text["versions.tf"]
    assert "import {" in text["main.tf"]
    assert "to = google_storage_bucket.bucket_stray_bucket" in text["main.tf"]
    assert "demo-project/stray-bucket" in text["main.tf"]


def _logging_tofu(tmp_path: Path, fail: str | None = None) -> tuple[Path, Path]:
    binary = tmp_path / "fake-tofu"
    log = tmp_path / "calls.log"
    binary.write_text(
        f"""#!/bin/sh
echo "$@" >> "{log}"
if [ "$1" = "{fail or "never"}" ]; then
  echo "boom" >&2
  exit 1
fi
exit 0
""",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary, log


def test_reaper_adopts_then_destroys(tmp_path: Path, inventory: None) -> None:
    stack = _stack()
    plan = discover(stack, ("buckets",))
    binary, log = _logging_tofu(tmp_path)

    Reaper(tmp_path, GcpRenderer(tmp_path), stack, binary=str(binary)).reap(plan.resources)

    assert log.read_text().splitlines() == [
        "init -input=false",
        "apply -no-color -auto-approve",
        "destroy -no-color -auto-approve",
    ]
    assert not (tmp_path / Reaper.DIRECTORY).exists()


def test_reaper_keeps_scratch_on_failure(tmp_path: Path, inventory: None) -> None:
    stack = _stack()
    plan = discover(stack, ("buckets",))
    binary, _log = _logging_tofu(tmp_path, fail="apply")

    with pytest.raises(PruneError, match="prune adopt failed"):
        Reaper(tmp_path, GcpRenderer(tmp_path), stack, binary=str(binary)).reap(plan.resources)

    assert (tmp_path / Reaper.DIRECTORY / "main.tf").is_file()


# ── CLI ───────────────────────────────────────────────────────────────
def _write_config(
    tmp_path: Path,
    enabled: bool,
    include_service_accounts: bool = False,
    sections: tuple[str, ...] | None = None,
) -> Path:
    options: list[str] = []
    if enabled:
        options.append("enabled=True")
    if include_service_accounts:
        options.append("include_service_accounts=True")
    if sections is not None:
        options.append(f"sections={sections!r}")
    prune = f"prune=PruneConfig({', '.join(options)})," if options else ""
    path = tmp_path / "infra.py"
    path.write_text(
        f"""\
from python_tofu import (
    GcpProvider,
    GcpStack,
    PruneConfig,
    ProjectApi,
    ServiceAccount,
    StorageBucket,
)

stack = GcpStack(
    provider=GcpProvider(project="demo-project"),
    {prune}
    buckets=[StorageBucket(project="demo-project", name="declared-bucket")],
    service_accounts=[ServiceAccount(project="demo-project", account_id="ci-runner")],
    apis=[ProjectApi(project="demo-project", service="storage.googleapis.com")],
    external_buckets=["external-bucket"],
)
""",
        encoding="utf-8",
    )
    return path


def _combined(result: object) -> str:
    return str(getattr(result, "output", "")) + str(getattr(result, "stderr", ""))


def test_cli_prune_dry_run_lists_resources(
    runner: CliRunner, cli: object, tmp_path: Path, inventory: None
) -> None:
    config = _write_config(tmp_path, enabled=True)
    result = runner.invoke(
        cli,
        ["prune", "--config", str(config), "--workdir", str(tmp_path / "tofu")],
    )

    assert result.exit_code == 0, _combined(result)
    assert "Prune plan: 2 undeclared resource(s)" in result.output
    assert "stray-bucket" in result.output
    assert "service accounts are skipped" in _combined(result)
    assert "Dry run" in result.output


def test_cli_prune_requires_sections_when_disabled(
    runner: CliRunner, cli: object, tmp_path: Path
) -> None:
    config = _write_config(tmp_path, enabled=False)
    result = runner.invoke(cli, ["prune", "--config", str(config)])

    assert result.exit_code == 1
    assert "pruning is disabled in the stack" in _combined(result)


def test_cli_prune_section_overrides_disabled_config(
    runner: CliRunner, cli: object, tmp_path: Path, inventory: None
) -> None:
    config = _write_config(tmp_path, enabled=False)
    result = runner.invoke(
        cli,
        ["prune", "--config", str(config), "--section", "buckets"],
    )

    assert result.exit_code == 0, _combined(result)
    assert "Prune plan: 1 undeclared resource(s)" in result.output


def test_cli_prune_apply_deletes(
    runner: CliRunner, cli: object, tmp_path: Path, inventory: None, fake_tofu: Path
) -> None:
    config = _write_config(tmp_path, enabled=True)
    result = runner.invoke(
        cli,
        [
            "prune",
            "--config",
            str(config),
            "--workdir",
            str(tmp_path / "tofu"),
            "--binary",
            str(fake_tofu),
            "--apply",
            "--auto-approve",
        ],
    )

    assert result.exit_code == 0, _combined(result)
    assert "Pruned 2 resource(s)." in result.output
    assert not (tmp_path / "tofu" / Reaper.DIRECTORY).exists()


def test_cli_plan_with_prune_previews_only(
    runner: CliRunner, cli: object, tmp_path: Path, inventory: None, fake_tofu: Path
) -> None:
    config = _write_config(tmp_path, enabled=True)
    result = runner.invoke(
        cli,
        [
            "plan",
            "--config",
            str(config),
            "--workdir",
            str(tmp_path / "tofu"),
            "--binary",
            str(fake_tofu),
            "--no-init",
        ],
    )

    assert result.exit_code == 0, _combined(result)
    assert "Prune plan: 2 undeclared resource(s)" in result.output
    assert "Dry run" in result.output


def test_cli_apply_with_prune_prunes_after_apply(
    runner: CliRunner, cli: object, tmp_path: Path, inventory: None, fake_tofu: Path
) -> None:
    config = _write_config(tmp_path, enabled=True)
    result = runner.invoke(
        cli,
        [
            "apply",
            "--config",
            str(config),
            "--workdir",
            str(tmp_path / "tofu"),
            "--binary",
            str(fake_tofu),
            "--auto-approve",
        ],
    )

    assert result.exit_code == 0, _combined(result)
    assert "Pruned 2 resource(s)." in result.output


def test_cli_prune_explain_lists_skipped_bindings(
    runner: CliRunner,
    cli: object,
    tmp_path: Path,
    inventory: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_config(tmp_path, enabled=True, sections=("project_iam",))
    monkeypatch.setattr(gcp_prune, "get_project_iam_bindings", lambda project, token: IAM_POLICY)

    result = runner.invoke(
        cli,
        ["prune", "--config", str(config), "--workdir", str(tmp_path / "tofu"), "--explain"],
    )

    assert result.exit_code == 0, _combined(result)
    assert "Skipped resources:" in result.output
    assert "user:alice@example.com roles/viewer (non-service-account)" in result.output
    assert "roles/owner (protected-role)" in result.output


def test_cli_prune_service_accounts_needs_both_gates(
    runner: CliRunner, cli: object, tmp_path: Path, inventory: None
) -> None:
    config = _write_config(tmp_path, enabled=True, include_service_accounts=True)

    blocked = runner.invoke(
        cli,
        ["prune", "--config", str(config), "--section", "service_accounts"],
    )
    assert blocked.exit_code == 1
    assert "--allow-service-accounts" in _combined(blocked)

    allowed = runner.invoke(
        cli,
        [
            "prune",
            "--config",
            str(config),
            "--section",
            "service_accounts",
            "--allow-service-accounts",
        ],
    )
    assert allowed.exit_code == 0, _combined(allowed)
    assert "service account manual@demo-project.iam.gserviceaccount.com" in allowed.output


def test_cli_prune_all_skips_service_accounts_without_run_gate(
    runner: CliRunner, cli: object, tmp_path: Path, inventory: None
) -> None:
    config = _write_config(tmp_path, enabled=True, include_service_accounts=True)

    skipped = runner.invoke(cli, ["prune", "--config", str(config), "--all"])
    assert skipped.exit_code == 0, _combined(skipped)
    assert "Prune plan: 2 undeclared resource(s)" in skipped.output
    assert "service accounts are skipped" in _combined(skipped)

    allowed = runner.invoke(
        cli,
        ["prune", "--config", str(config), "--all", "--allow-service-accounts"],
    )
    assert allowed.exit_code == 0, _combined(allowed)
    assert "Prune plan: 3 undeclared resource(s)" in allowed.output


def test_cli_apply_prune_never_runs_project_iam(
    runner: CliRunner,
    cli: object,
    tmp_path: Path,
    inventory: None,
    fake_tofu: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_config(tmp_path, enabled=True, sections=("project_iam",))
    monkeypatch.setattr(
        gcp_prune,
        "get_project_iam_bindings",
        lambda project, token: [
            {
                "role": "roles/viewer",
                "members": ["serviceAccount:ci-runner@demo-project.iam.gserviceaccount.com"],
            }
        ],
    )

    result = runner.invoke(
        cli,
        [
            "apply",
            "--config",
            str(config),
            "--workdir",
            str(tmp_path / "tofu"),
            "--binary",
            str(fake_tofu),
            "--auto-approve",
        ],
    )

    assert result.exit_code == 0, _combined(result)
    assert "never pruned by apply --prune" in _combined(result)
    assert "Pruned" not in result.output


def test_cli_apply_prune_with_plan_file_fails(
    runner: CliRunner, cli: object, tmp_path: Path
) -> None:
    config = _write_config(tmp_path, enabled=False)
    workdir = tmp_path / "tofu"
    workdir.mkdir()
    result = runner.invoke(
        cli,
        [
            "apply",
            "--config",
            str(config),
            "--workdir",
            str(workdir),
            "--plan-file",
            str(workdir / "plan.tfplan"),
            "--prune",
        ],
    )

    assert result.exit_code == 1
    assert "--prune cannot be combined with --plan-file" in _combined(result)


def test_gcp_provider_advertises_pruning() -> None:
    assert GCP.can_prune
    assert GCP.prune_sections == GCP_PRUNE_SECTIONS
