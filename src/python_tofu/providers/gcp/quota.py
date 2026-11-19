"""Service Usage consumer quota overrides: ceilings the cloud itself enforces.

GCP has no hard spend cap, so a :class:`BillingBudget` only emails. A consumer
quota override is enforced by the Service Usage API: once a project reaches the
override it cannot create more of that resource, whoever applies.

The OpenTofu resource for this (``google_service_usage_consumer_quota_override``)
is beta-only, while the Nix build mirrors only ``hashicorp/google`` and keeps
``tofu init`` offline. So the wrapper reconciles the section through the API
directly — the same split ``prune`` already uses for discovery.

``discover`` never writes. ``apply_plan`` creates or updates only the overrides
the stack declares; overrides that exist in the project without a declaration
are reported as warnings rather than deleted, because an admin-set ceiling is
not the stack's to remove.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from python_tofu.core.quota import QuotaChange, QuotaPlan
from python_tofu.providers.gcp.live import (
    GoogleApiError,
    access_token,
    get_json,
    patch_json,
    post_json,
)
from python_tofu.providers.gcp.stack import GcpStack

QUOTA_BASE = "https://serviceusage.googleapis.com/v1beta1"


def format_value(value: float) -> str:
    """Render an override value the way the API does (``0``, not ``0.0``)."""

    return f"{value:g}"


def _quote(value: str) -> str:
    """Quote a path segment. Metric and limit both contain ``/``, so nothing stays bare."""

    return urllib.parse.quote(value, safe="")


def limit_path(project: str, service: str, metric: str, limit: str) -> str:
    """Return the Service Usage resource path of the limit an override attaches to."""

    return (
        f"projects/{_quote(project)}/services/{_quote(service)}"
        f"/consumerQuotaMetrics/{_quote(metric)}/limits/{_quote(limit)}"
    )


def list_overrides(path: str, token: str) -> list[dict[str, Any]]:
    """Return the consumer overrides attached to ``path`` (a limit resource)."""

    url = f"{QUOTA_BASE}/{path}/consumerOverrides"
    overrides: list[dict[str, Any]] = []
    params: dict[str, str] = {"pageSize": "200"}
    while True:
        payload = get_json(url, token, params)
        overrides.extend(payload.get("overrides", []))
        page = payload.get("nextPageToken")
        if not page:
            return overrides
        params = {**params, "pageToken": str(page)}


def _address(project: str, service: str, metric: str, limit: str) -> str:
    return f"{metric} {limit} in {project}"


def _value_of(raw: dict[str, Any]) -> str | None:
    value = raw.get("overrideValue")
    if value is None:
        return None
    try:
        return format_value(float(value))
    except (TypeError, ValueError):
        return str(value)


def discover(stack: GcpStack) -> QuotaPlan:
    """Compare the declared overrides with the live ones. Read-only."""

    token = access_token(stack)
    changes: list[QuotaChange] = []
    warnings: list[str] = []

    # Collapse duplicates first: a limit carries one override, so reconciling
    # the last declaration is the only behaviour that keeps the stack
    # authoritative regardless of list order.
    selected: dict[tuple[str, str, str, str], Any] = {}
    for override in stack.quota_overrides:
        key = (override.project, override.service, override.metric, override.limit)
        if key in selected:
            warnings.append(
                f"{_address(*key)} is declared more than once; the last declaration wins"
            )
        selected[key] = override

    for key, override in selected.items():
        path = limit_path(*key)
        try:
            live = list_overrides(path, token)
        except GoogleApiError as exc:
            if exc.status == 404:
                warnings.append(
                    f"{_address(*key)}: no such limit on this project — check "
                    "`metric` and `limit` against the Service Usage API "
                    "(`gcloud alpha services quota list --service=<service> "
                    "--consumer=projects/<project>`)"
                )
                continue
            raise

        address = _address(*key)
        desired = format_value(override.value)
        if not live:
            changes.append(
                QuotaChange(
                    action="create",
                    address=address,
                    desired=desired,
                    handle=path,
                    force=override.force,
                )
            )
            continue

        if len(live) > 1:
            warnings.append(
                f"{address}: {len(live)} consumer overrides exist; reconciling the first"
            )
        current = _value_of(live[0])
        if current == desired:
            continue
        changes.append(
            QuotaChange(
                action="update",
                address=address,
                current=current,
                desired=desired,
                handle=str(live[0].get("name") or ""),
                force=override.force,
            )
        )

    if not stack.quota_overrides:
        warnings.append("no quota overrides declared")
    return QuotaPlan(changes=tuple(changes), warnings=tuple(warnings))


def apply_plan(stack: GcpStack, plan: QuotaPlan) -> None:
    """Create or update every override in ``plan`` through the Service Usage API."""

    if plan.empty:
        return
    token = access_token(stack)
    for change in plan.changes:
        force = "true" if change.force else "false"
        if change.is_create:
            url = f"{QUOTA_BASE}/{change.handle}/consumerOverrides?force={force}"
            post_json(url, token, {"overrideValue": change.desired})
        else:
            if not change.handle:
                raise GoogleApiError(
                    f"cannot update {change.address}: the live override has no resource name"
                )
            url = f"{QUOTA_BASE}/{change.handle}?force={force}"
            patch_json(url, token, {"overrideValue": change.desired})


__all__ = [
    "QUOTA_BASE",
    "apply_plan",
    "discover",
    "format_value",
    "limit_path",
    "list_overrides",
]
