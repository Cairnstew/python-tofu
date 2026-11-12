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
CAI_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# Always-free Compute Engine regions.
FREE_COMPUTE_REGIONS = frozenset({"us-central1", "us-east1", "us-west1"})

# A conservative month: February is shorter, so 720 never understates.
HOURS_PER_MONTH = 720.0

_ZONE_RE = re.compile(r"^[a-z]+-[a-z]+\d+-[a-z]$")
DISK_TYPE = "compute.googleapis.com/Disk"
INSTANCE_TYPE = "compute.googleapis.com/Instance"
CLUSTER_TYPE = "container.googleapis.com/Cluster"


class LiveUsageError(TofuError):
    """Raised when live inventory measurement cannot be completed."""


def _access_token(stack: GcpStack) -> str:
    """Return an OAuth token for the stack's credentials (ADC fallback)."""

    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise LiveUsageError(
            "live usage requires google-auth; reinstall python-tofu or run "
            "`uv sync` to restore dependencies"
        ) from exc

    scopes = [CAI_SCOPE]
    credentials_path = stack.provider.credentials or os.environ.get(
        "GOOGLE_APPLICATION_CREDENTIALS"
    )
    try:
        if credentials_path:
            loader = service_account.Credentials.from_service_account_file
            credentials = loader(  # type: ignore[no-untyped-call]
                credentials_path, scopes=scopes
            )
        else:
            import google.auth

            credentials, _ = google.auth.default(scopes=scopes)
        credentials.refresh(Request())
    except Exception as exc:  # google-auth raises several unrelated types
        raise LiveUsageError(f"could not obtain Google credentials: {exc}") from exc

    token = getattr(credentials, "token", None)
    if not token:
        raise LiveUsageError("Google credentials returned no access token")
    return str(token)


def _get_json(url: str, token: str, params: dict[str, str]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)  # type: ignore[no-any-return]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise LiveUsageError(
            f"Cloud Asset Inventory returned {exc.code} for {url}: {detail}"
        ) from None
    except urllib.error.URLError as exc:
        raise LiveUsageError(f"could not reach Cloud Asset Inventory: {exc.reason}") from None


def _list_assets(project: str, token: str, asset_type: str) -> list[dict[str, Any]]:
    """Return ``resource.data`` for every asset of ``asset_type`` in ``project``."""

    url = f"{CAI_BASE}/projects/{project}/assets"
    params = {"assetTypes": asset_type, "contentType": "RESOURCE", "pageSize": "500"}
    resources: list[dict[str, Any]] = []
    while True:
        payload = _get_json(url, token, params)
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

    token = _access_token(stack)
    project = stack.provider.project

    instances = _list_assets(project, token, INSTANCE_TYPE)
    micro_hours = HOURS_PER_MONTH * sum(1 for data in instances if _is_free_tier_e2_micro(data))

    disks = _list_assets(project, token, DISK_TYPE)
    disk_gb = sum(_disk_size_gb(data) for data in disks if _is_free_tier_disk(data))

    clusters = _list_assets(project, token, CLUSTER_TYPE)
    free_clusters = sum(1 for data in clusters if _is_free_tier_cluster(data))

    return (
        Usage()
        .add("gcp.compute.e2_micro_hours", micro_hours)
        .add("gcp.compute.standard_pd_gb", disk_gb)
        .add("gcp.gke.free_clusters", free_clusters)
    )


__all__ = [
    "FREE_COMPUTE_REGIONS",
    "HOURS_PER_MONTH",
    "LiveUsageError",
    "live_measure_usage",
]
