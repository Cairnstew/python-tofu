"""Read-only preflight checks for GCP stacks.

Wired into the generic ``doctor`` command through
:attr:`python_tofu.core.provider.Provider.doctor_checks`. Every call is a GET:
nothing is enabled, created or deleted. Each result carries the command that
fixes it, so a failure costs seconds instead of a failed apply.
"""

from __future__ import annotations

import json
import os
import urllib.parse
from pathlib import Path
from typing import Any

from python_tofu.core.doctor import CheckResult, CheckStatus
from python_tofu.core.exceptions import TofuError
from python_tofu.providers.gcp import live
from python_tofu.providers.gcp.apis import declared_apis
from python_tofu.providers.gcp.models import GcpBackendConfig
from python_tofu.providers.gcp.services import ServiceCatalog
from python_tofu.providers.gcp.stack import GcpStack

CLOUD_RESOURCE_MANAGER = "https://cloudresourcemanager.googleapis.com/v1"
CLOUD_BILLING = "https://cloudbilling.googleapis.com/v1"
STORAGE = "https://storage.googleapis.com/storage/v1"
TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"

LOGIN_FIX = "gcloud auth application-default login"


def _ok(name: str, message: str) -> CheckResult:
    return CheckResult(name, CheckStatus.OK, message)


def _fail(name: str, message: str, fix: str | None = None) -> CheckResult:
    return CheckResult(name, CheckStatus.FAIL, message, fix=fix)


def _unknown(name: str, message: str, fix: str | None = None) -> CheckResult:
    return CheckResult(name, CheckStatus.UNKNOWN, message, fix=fix)


def _skip(name: str, message: str) -> CheckResult:
    return CheckResult(name, CheckStatus.SKIP, message)


def _tokeninfo(token: str) -> dict[str, Any]:
    """Best-effort identity/expiry for the minted token; never fatal."""

    try:
        return live.get_json(TOKENINFO, token, {"access_token": token})
    except live.GoogleApiError:
        return {}


def check_credentials(stack: GcpStack) -> tuple[CheckResult, str | None]:
    try:
        token = live.access_token(stack)
    except TofuError as exc:
        return _fail("credentials", str(exc), fix=LOGIN_FIX), None

    message = "access token minted"
    info = _tokeninfo(token)
    email = str(info.get("email") or "")
    key_path = stack.provider.credentials or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not email and key_path:
        # Service-account keys carry the identity locally; tokeninfo may omit it.
        try:
            with open(os.path.expanduser(key_path), encoding="utf-8") as handle:
                email = str(json.load(handle).get("client_email") or "")
        except (OSError, ValueError):
            email = ""
    expires = info.get("expires_in")
    if email:
        message = email
    try:
        if expires is not None:
            minutes = int(expires) // 60
            suffix = f" (expires in {minutes}m)" if minutes else " (expires soon)"
            message += suffix
    except (TypeError, ValueError):
        pass
    return _ok("credentials", message), token


def check_project(stack: GcpStack, token: str) -> CheckResult:
    project = stack.provider.project
    try:
        payload = live.get_json(f"{CLOUD_RESOURCE_MANAGER}/projects/{project}", token, {})
    except live.GoogleApiError as exc:
        if exc.status == 404:
            return _fail(
                "project",
                f"{project} does not exist",
                fix="check provider.project / GOOGLE_PROJECT and the project id",
            )
        if exc.status == 403:
            return _fail(
                "project",
                f"cannot read {project}: permission denied",
                fix=f"grant roles/viewer on {project} to the calling identity",
            )
        return _unknown("project", f"could not read {project}: {exc}")

    state = str(payload.get("lifecycleState") or "UNKNOWN")
    if state == "ACTIVE":
        name = payload.get("name")
        label = (
            f"{project} (ACTIVE)" if not name or name == project else f"{project} (ACTIVE, {name})"
        )
        return _ok("project", label)
    return _fail(
        "project",
        f"{project} lifecycle state is {state}",
        fix=f"gcloud projects describe {project}",
    )


def check_billing(stack: GcpStack, token: str) -> CheckResult:
    project = stack.provider.project
    try:
        payload = live.get_json(f"{CLOUD_BILLING}/projects/{project}/billingInfo", token, {})
    except live.GoogleApiError as exc:
        if exc.status in (401, 403):
            return _unknown(
                "billing",
                "cannot read billing info: permission denied",
                fix=f"grant roles/billing.viewer on {project}",
            )
        return _unknown("billing", f"could not read billing info: {exc}")

    if payload.get("billingEnabled"):
        account = str(payload.get("billingAccountName") or "").rsplit("/", 1)[-1]
        return _ok("billing", f"enabled ({account})" if account else "enabled")
    return _fail(
        "billing",
        "billing is disabled; most resources cannot be created",
        fix=f"gcloud billing projects link {project} --billing-account=<ACCOUNT_ID>",
    )


def check_apis(stack: GcpStack, token: str) -> list[CheckResult]:
    owned = {stack.provider.project, *(project.project_id for project in stack.projects)}
    wanted: dict[str, set[str]] = {}
    for api in declared_apis(stack):
        if api.project in owned:
            wanted.setdefault(api.project, set()).add(api.service)

    if not wanted:
        return [_skip("APIs", "the stack neither declares nor derives any APIs")]

    results: list[CheckResult] = []
    for project in sorted(wanted):
        name = "APIs" if project == stack.provider.project else f"APIs ({project})"
        required = wanted[project]
        try:
            enabled = {service.name for service in ServiceCatalog(project, token=token).enabled()}
        except TofuError as exc:
            results.append(_unknown(name, f"could not list enabled services: {exc}"))
            continue

        missing = sorted(required - enabled)
        if missing:
            results.append(
                _fail(
                    name,
                    f"{len(missing)} of {len(required)} required disabled: {', '.join(missing)}",
                    fix=f"gcloud services enable {' '.join(missing)} --project {project}",
                )
            )
        else:
            results.append(_ok(name, f"{len(required)} required, all ENABLED"))
    return results


def _local_backend(stack: GcpStack, workdir: Path) -> CheckResult:
    backend = stack.backend
    if isinstance(backend, GcpBackendConfig) and backend.kind == "local":
        target = Path(backend.path or "terraform.tfstate").expanduser()
        if not target.is_absolute():
            target = Path(workdir) / target
        directory = target.parent if target.suffix else target
    else:
        directory = Path(workdir)

    if directory.exists():
        if not directory.is_dir():
            return _fail("backend", f"{directory} exists but is not a directory")
        if not os.access(directory, os.W_OK):
            return _fail("backend", f"{directory} is not writable", fix=f"chmod u+w {directory}")
        return _ok("backend", f"local state in {directory}")

    ancestor = directory
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if not ancestor.exists() or not os.access(ancestor, os.W_OK):
        return _fail(
            "backend",
            f"{directory} cannot be created",
            fix=f"create it or pick another --workdir: mkdir -p {directory}",
        )
    return _ok("backend", f"local state in {directory} (creatable)")


def check_backend(stack: GcpStack, token: str, workdir: Path) -> CheckResult:
    backend = stack.backend
    if backend is None or backend.kind != "gcs":
        return _local_backend(stack, workdir)

    bucket = str(backend.bucket)
    prefix = backend.prefix_for(stack.name)
    try:
        live.get_json(f"{STORAGE}/b/{bucket}", token, {})
    except live.GoogleApiError as exc:
        if exc.status == 404:
            return _fail(
                "backend",
                f"gs://{bucket} does not exist",
                fix=(
                    f"create it with: gcloud storage buckets create gs://{bucket} "
                    "--location=<REGION>"
                ),
            )
        if exc.status in (401, 403):
            return _fail(
                "backend",
                f"cannot read gs://{bucket}: permission denied",
                fix=f"grant roles/storage.admin on gs://{bucket}",
            )
        return _unknown("backend", f"could not reach gs://{bucket}: {exc}")

    return _ok("backend", f"gs://{bucket} prefix {prefix}")


def check_state_lock(stack: GcpStack, token: str) -> CheckResult:
    backend = stack.backend
    if backend is None or backend.kind != "gcs":
        return _skip("state lock", "only GCS backends store a lock object")

    bucket = str(backend.bucket)
    prefix = backend.prefix_for(stack.name)
    workspace = os.environ.get("TF_WORKSPACE") or "default"
    lock = f"{prefix}/{workspace}.tflock"
    object_path = urllib.parse.quote(lock, safe="")
    try:
        live.get_json(f"{STORAGE}/b/{bucket}/o/{object_path}", token, {})
    except live.GoogleApiError as exc:
        if exc.status == 404:
            return _ok("state lock", "none")
        if exc.status in (401, 403):
            return _unknown("state lock", "cannot read the lock object: permission denied")
        return _unknown("state lock", f"could not read the lock object: {exc}")

    return _fail(
        "state lock",
        f"present: gs://{bucket}/{lock}; another apply may be running",
        fix="wait for it to finish, or force-unlock if it is stale",
    )


def run_checks(stack: GcpStack, workdir: Path) -> list[CheckResult]:
    """Run every GCP preflight check in order."""

    credentials, token = check_credentials(stack)
    results = [credentials]
    if token is None:
        for name in ("project", "billing", "APIs", "backend", "state lock"):
            results.append(_unknown(name, "not checked: credentials unavailable"))
        return results

    results.append(check_project(stack, token))
    results.append(check_billing(stack, token))
    results.extend(check_apis(stack, token))
    results.append(check_backend(stack, token, workdir))
    results.append(check_state_lock(stack, token))
    return results


__all__ = [
    "check_apis",
    "check_backend",
    "check_billing",
    "check_credentials",
    "check_project",
    "check_state_lock",
    "run_checks",
]
