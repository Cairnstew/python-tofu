"""Live, read-only inventory measurement via Cloud Asset Inventory.

This accounts for resources that exist in the project whether or not the stack
declares them — manually created or pre-existing infrastructure included. It is
deliberately read-only: every call is a Cloud Asset Inventory ``assets.list``
GET (the ``searchAllResources`` POST route 404s on this API version).

What can be measured from inventory metadata:

- ``gcp.compute.e2_micro_hours`` — non-preemptible ``e2-micro`` instances in a
  free-tier region count as a full 720-hour month (a conservative pre-flight).
- ``gcp.compute.standard_pd_gb`` — ``pd-standard`` disk size in a free region.
- ``gcp.gke.free_clusters`` — Autopilot or zonal Standard clusters.

Byte-based limits (bucket size, BigQuery storage, egress, request counts) are
**not** in inventory metadata. They stay ``unknown`` unless the stack supplies
``usage_estimates`` — never silently zero.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from python_tofu.core.exceptions import TofuError
from python_tofu.core.limits import Usage
from python_tofu.providers.gcp.stack import GcpStack

CAI_BASE = "https://cloudasset.googleapis.com/v1"
#: Scope shared by Cloud Asset Inventory and Service Usage reads.
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
CAI_SCOPE = CLOUD_PLATFORM_SCOPE

# Always-free Compute Engine regions.
FREE_COMPUTE_REGIONS = frozenset({"us-central1", "us-east1", "us-west1"})

# A conservative month: February is shorter, so 720 never understates.
HOURS_PER_MONTH = 720.0

_ZONE_RE = re.compile(r"^[a-z]+-[a-z]+\d+-[a-z]$")
DISK_TYPE = "compute.googleapis.com/Disk"
INSTANCE_TYPE = "compute.googleapis.com/Instance"
CLUSTER_TYPE = "container.googleapis.com/Cluster"


class GoogleApiError(TofuError):
    """Raised when a read-only Google API call cannot be completed."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


#: Backwards-compatible name: live measurement was the first user of the client.
LiveUsageError = GoogleApiError


def _normalise_impersonation(target: str | None) -> str | None:
    """Return a bare service-account email, or ``None`` when impersonation is off."""

    if not target:
        return None
    value = target.strip()
    prefix = "serviceAccount:"
    if value.startswith(prefix):
        value = value[len(prefix) :]
    if "@" not in value:
        raise GoogleApiError(
            f"impersonate_service_account must be a service-account email: {target!r}"
        )
    return value


def access_token_for(
    credentials_path: str | None = None,
    impersonate_service_account: str | None = None,
) -> str:
    """Return an OAuth token for a key path (ADC fallback).

    When ``impersonate_service_account`` is set, the source credential mints a
    token for that service account through the IAM Credentials API. This keeps
    the wrapper's read-only calls (doctor, limits, prune) on the same effective
    identity the rendered provider block uses, instead of silently falling back
    to the broad provisioning key.
    """

    target = _normalise_impersonation(impersonate_service_account)

    try:
        from google.auth import impersonated_credentials
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise GoogleApiError(
            "Google API access requires google-auth; reinstall python-tofu or run "
            "`uv sync` to restore dependencies"
        ) from exc

    scopes = [CLOUD_PLATFORM_SCOPE]
    path = credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    try:
        if path:
            loader = service_account.Credentials.from_service_account_file
            source = loader(path, scopes=scopes)  # type: ignore[no-untyped-call]
        else:
            import google.auth

            source, _ = google.auth.default(scopes=scopes)

        creds = source
        if target:
            creds = impersonated_credentials.Credentials(  # type: ignore[no-untyped-call]
                source_credentials=source,
                target_principal=target,
                target_scopes=scopes,
                lifetime=3600,
            )
        creds.refresh(Request())
    except Exception as exc:  # google-auth raises several unrelated types
        suffix = f" as {target}" if target else ""
        raise GoogleApiError(f"could not obtain Google credentials{suffix}: {exc}") from exc

    token = getattr(creds, "token", None)
    if not token:
        raise GoogleApiError("Google credentials returned no access token")
    return str(token)


def _identity_email(value: str | None) -> str | None:
    """Return a service-account email from an email or ``serviceAccount:`` form."""

    if not value:
        return None
    candidate = value.strip()
    prefix = "serviceAccount:"
    if candidate.startswith(prefix):
        candidate = candidate[len(prefix) :]
    return candidate.lower() if "@" in candidate else None


def _key_email(credentials_path: str | None) -> str | None:
    """Read ``client_email`` from a service-account JSON key without a token call."""

    if not credentials_path:
        return None
    try:
        with open(os.path.expanduser(credentials_path), encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError):
        return None
    email = payload.get("client_email") if isinstance(payload, dict) else None
    return str(email).lower() if email else None


def credential_identities(
    credentials_path: str | None = None,
    impersonate_service_account: str | None = None,
) -> frozenset[str]:
    """Service-account emails the active credential represents.

    This is deliberately best-effort and local: a key file gives an exact
    ``client_email``, impersonation gives the target, and ADC service accounts
    expose ``service_account_email``. Prune uses it to protect the identity that
    runs the tool, so a missing value must never become a false "safe to delete".
    """

    identities: set[str] = set()
    target = _identity_email(impersonate_service_account)
    if target is not None:
        identities.add(target)

    key_email = _key_email(credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
    if key_email is not None:
        identities.add(key_email)

    if not identities:
        try:
            import google.auth

            creds, _ = google.auth.default()
            email = getattr(creds, "service_account_email", None)
            if email:
                identities.add(str(email).lower())
        except Exception:  # google-auth raises several unrelated types
            pass

    return frozenset(identities)


def access_token(stack: GcpStack) -> str:
    """Return an OAuth token for the stack's credentials (ADC fallback)."""

    return access_token_for(
        stack.provider.credentials,
        impersonate_service_account=stack.provider.impersonate_service_account,
    )


def get_json(
    url: str,
    token: str,
    params: dict[str, str],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    merged = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if headers:
        merged.update(headers)
    scheme = urllib.parse.urlparse(url).scheme
    if scheme not in ("https", "http"):
        raise GoogleApiError(f"refusing to call a non-HTTP URL: {url}")
    request = urllib.request.Request(f"{url}?{query}", headers=merged)
    try:
        # The scheme is restricted to http(s) immediately above.
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
            return json.load(response)  # type: ignore[no-any-return]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise GoogleApiError(
            f"Google API returned {exc.code} for {url}: {detail}", status=exc.code
        ) from None
    except urllib.error.URLError as exc:
        raise GoogleApiError(f"could not reach Google API {url}: {exc.reason}") from None


def post_json(
    url: str,
    token: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """POST a JSON body and decode the JSON response (read-only APIs that need a body)."""

    merged = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if headers:
        merged.update(headers)
    scheme = urllib.parse.urlparse(url).scheme
    if scheme not in ("https", "http"):
        raise GoogleApiError(f"refusing to call a non-HTTP URL: {url}")
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers=merged)
    try:
        # The scheme is restricted to http(s) immediately above.
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
            return json.load(response)  # type: ignore[no-any-return]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise GoogleApiError(
            f"Google API returned {exc.code} for {url}: {detail}", status=exc.code
        ) from None
    except urllib.error.URLError as exc:
        raise GoogleApiError(f"could not reach Google API {url}: {exc.reason}") from None


def list_assets(project: str, token: str, asset_type: str) -> list[dict[str, Any]]:
    """Return ``resource.data`` for every asset of ``asset_type`` in ``project``."""

    url = f"{CAI_BASE}/projects/{project}/assets"
    params = {"assetTypes": asset_type, "contentType": "RESOURCE", "pageSize": "500"}
    resources: list[dict[str, Any]] = []
    while True:
        payload = get_json(url, token, params)
        for asset in payload.get("assets", []):
            data = (asset.get("resource") or {}).get("data")
            if isinstance(data, dict):
                resources.append(data)
        token_next = payload.get("nextPageToken")
        if not token_next:
            return resources
        params["pageToken"] = str(token_next)


def _region(location: str) -> str:
    value = _basename(location).lower()
    return value.rsplit("-", 1)[0] if _ZONE_RE.match(value) else value


def _basename(value: Any) -> str:
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def _is_free_tier_e2_micro(data: dict[str, Any]) -> bool:
    if _basename(data.get("machineType")) != "e2-micro":
        return False
    if _region(str(data.get("zone", ""))) not in FREE_COMPUTE_REGIONS:
        return False
    scheduling = data.get("scheduling") or {}
    return not scheduling.get("preemptible") and scheduling.get("provisioningModel") != "SPOT"


def _is_free_tier_disk(data: dict[str, Any]) -> bool:
    if _basename(data.get("type")) != "pd-standard":
        return False
    return _region(str(data.get("zone", ""))) in FREE_COMPUTE_REGIONS


def _disk_size_gb(data: dict[str, Any]) -> float:
    try:
        return float(data.get("sizeGb") or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_free_tier_cluster(data: dict[str, Any]) -> bool:
    # One Autopilot cluster or one zonal Standard cluster is free; regional
    # Standard clusters are not.
    if bool((data.get("autopilot") or {}).get("enabled")):
        return True
    return bool(_ZONE_RE.match(str(data.get("location", "")).lower()))


def live_measure_usage(stack: GcpStack) -> Usage:
    """Measure pre-existing GCP infrastructure that maps to countable limits."""

    token = access_token(stack)
    project = stack.provider.project

    instances = list_assets(project, token, INSTANCE_TYPE)
    micro_hours = HOURS_PER_MONTH * sum(1 for data in instances if _is_free_tier_e2_micro(data))

    disks = list_assets(project, token, DISK_TYPE)
    disk_gb = sum(_disk_size_gb(data) for data in disks if _is_free_tier_disk(data))

    clusters = list_assets(project, token, CLUSTER_TYPE)
    free_clusters = sum(1 for data in clusters if _is_free_tier_cluster(data))

    return (
        Usage()
        .add("gcp.compute.e2_micro_hours", micro_hours)
        .add("gcp.compute.standard_pd_gb", disk_gb)
        .add("gcp.gke.free_clusters", free_clusters)
    )


__all__ = [
    "CLOUD_PLATFORM_SCOPE",
    "FREE_COMPUTE_REGIONS",
    "GoogleApiError",
    "HOURS_PER_MONTH",
    "LiveUsageError",
    "access_token",
    "access_token_for",
    "credential_identities",
    "get_json",
    "list_assets",
    "live_measure_usage",
    "post_json",
]
