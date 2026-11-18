"""Declare enabled Google APIs through the Service Usage API.

The typed models already let you write ``ProjectApi(project=..., service=...)``
by hand. This module adds the missing discovery half: ask Google which services
exist for the project, which are enabled, and resolve short names such as
``compute`` to the canonical ``compute.googleapis.com`` deterministically.

Typical config use:

.. code-block:: python

    from python_tofu import GcpProvider, GcpStack
    from python_tofu.providers.gcp.services import ServiceCatalog

    provider = GcpProvider(project="my-project")
    catalog = ServiceCatalog(provider.project, credentials=provider.credentials)

    stack = GcpStack(provider=provider, apis=catalog.enable("compute", "storage"))

The catalog caches what it fetches for the process. Short and full names are
resolved with the per-service ``services.get`` endpoint, which is not affected
by the rate limit on listings; ``available()`` / ``all()`` use the
``state:DISABLED`` listing that Google throttles hard (often one request per
minute), and report a 429 with a hint when that quota is exhausted.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any, Iterable

from python_tofu.core.exceptions import TofuError
from python_tofu.providers.gcp.live import GoogleApiError, access_token_for, get_json
from python_tofu.providers.gcp.models import ProjectApi

SERVICE_USAGE_BASE = "https://serviceusage.googleapis.com/v1"
PAGE_SIZE = 200
ENABLED = "ENABLED"
DISABLED = "DISABLED"


class ServiceUsageError(TofuError):
    """Raised when a Service Usage lookup or name resolution fails."""


class UnknownService(ServiceUsageError):
    """The requested service is not in the project's Service Usage catalog."""

    def __init__(self, name: str, suggestions: Iterable[str] = ()) -> None:
        hints = sorted(suggestions)
        message = f"unknown Google API {name!r}"
        if hints:
            message += "; did you mean: " + ", ".join(hints)
        super().__init__(message)
        self.name = name
        self.suggestions = tuple(hints)


class AmbiguousService(ServiceUsageError):
    """A short or partial name matched more than one service."""

    def __init__(self, name: str, matches: Iterable[str]) -> None:
        choices = sorted(matches)
        super().__init__(f"ambiguous Google API {name!r}; choose one of: " + ", ".join(choices))
        self.name = name
        self.matches = tuple(choices)


@dataclass(frozen=True)
class Service:
    """One entry from ``projects/*/services``."""

    name: str
    title: str = ""
    state: str = "STATE_UNSPECIFIED"
    parent: str = ""

    @property
    def enabled(self) -> bool:
        return self.state.upper() == ENABLED

    @property
    def available(self) -> bool:
        return self.state.upper() == DISABLED

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "title": self.title,
            "state": self.state.lower(),
            "parent": self.parent,
        }


def canonical_service(name: str) -> str:
    """Return the full service name, adding ``.googleapis.com`` to a short name."""

    value = name.strip().lower()
    if not value:
        raise ServiceUsageError("service name must not be empty")
    if "/" in value:
        value = value.rsplit("/", 1)[-1]
    if "." not in value:
        value = f"{value}.googleapis.com"
    return value


def _parse_service(payload: dict[str, Any]) -> Service:
    config = payload.get("config") or {}
    name = str(config.get("name") or payload.get("name") or "").rsplit("/", 1)[-1]
    return Service(
        name=name,
        title=str(config.get("title") or ""),
        state=str(payload.get("state") or "STATE_UNSPECIFIED"),
        parent=str(payload.get("parent") or ""),
    )


def list_services(
    project: str,
    token: str,
    *,
    state: str | None = None,
    quota_project: str | None = None,
) -> list[Service]:
    """List services for ``project``, optionally filtered by ``state``.

    ``state="DISABLED"`` is what ``gcloud services list --available`` uses:
    services known to the project that can still be enabled. That listing is
    rate-limited by Google; enabled-only listings are not.
    """

    url = f"{SERVICE_USAGE_BASE}/projects/{project}/services"
    params: dict[str, str] = {"pageSize": str(PAGE_SIZE)}
    if state:
        params["filter"] = f"state:{state.upper()}"
    headers = {"x-goog-user-project": quota_project} if quota_project else None

    services: list[Service] = []
    query = dict(params)
    while True:
        try:
            payload = get_json(url, token, query, headers)
        except GoogleApiError as exc:
            if state and state.upper() == DISABLED and "429" in str(exc):
                raise ServiceUsageError(
                    f"{exc}\nHint: Service Usage rate-limits the available/disabled "
                    "listing. Wait about a minute, use --state enabled, or resolve an "
                    "already-enabled API."
                ) from exc
            raise
        services.extend(_parse_service(item) for item in payload.get("services", []))
        page = payload.get("nextPageToken")
        if not page:
            return services
        query = {**params, "pageToken": str(page)}


def get_service(
    project: str,
    token: str,
    name: str,
    *,
    quota_project: str | None = None,
) -> Service | None:
    """Fetch one service with ``services.get``; ``None`` when it does not exist."""

    service = canonical_service(name)
    url = f"{SERVICE_USAGE_BASE}/projects/{project}/services/{service}"
    headers = {"x-goog-user-project": quota_project} if quota_project else None
    try:
        payload = get_json(url, token, {}, headers)
    except GoogleApiError as exc:
        if exc.status == 404:
            return None
        raise
    return _parse_service(payload)


def _matches(service: Service, needle: str) -> bool:
    return needle in service.name.lower() or needle in service.title.lower()


def _filtered(services: Iterable[Service], filter: str | None) -> tuple[Service, ...]:
    if filter is None:
        return tuple(services)
    needle = filter.strip().lower()
    return tuple(item for item in services if _matches(item, needle))


class ServiceCatalog:
    """A cached view of the services Service Usage reports for one project."""

    def __init__(
        self,
        project: str,
        *,
        credentials: str | None = None,
        token: str | None = None,
        quota_project: str | None = None,
        impersonate_service_account: str | None = None,
    ) -> None:
        self.project = project
        self._credentials = credentials
        self._token = token
        self._quota_project = quota_project
        self._impersonate_service_account = impersonate_service_account
        self._enabled: tuple[Service, ...] | None = None
        self._available: tuple[Service, ...] | None = None
        self._all: tuple[Service, ...] | None = None
        self._direct: dict[str, Service | None] = {}

    def __repr__(self) -> str:
        return f"ServiceCatalog(project={self.project!r})"

    @property
    def token(self) -> str:
        if self._token is None:
            self._token = access_token_for(
                self._credentials,
                impersonate_service_account=self._impersonate_service_account,
            )
        return self._token

    def _fetch(self, state: str | None) -> tuple[Service, ...]:
        fetched = list_services(
            self.project,
            self.token,
            state=state,
            quota_project=self._quota_project,
        )
        return tuple(sorted(fetched, key=lambda item: item.name))

    def enabled(self, filter: str | None = None) -> tuple[Service, ...]:
        """Services already enabled (state ``ENABLED``); not rate-limited."""

        if self._enabled is None:
            self._enabled = self._fetch(ENABLED)
        return _filtered(self._enabled, filter)

    def available(self, filter: str | None = None) -> tuple[Service, ...]:
        """Services that can still be enabled (state ``DISABLED``)."""

        if self._available is None:
            self._available = self._fetch(DISABLED)
        return _filtered(self._available, filter)

    def all(self, filter: str | None = None) -> tuple[Service, ...]:
        """Every service known to the project, enabled and disabled."""

        if self._all is None:
            self._all = self._fetch(None)
        return _filtered(self._all, filter)

    def refresh(self) -> None:
        """Drop cached data so the next query re-reads Service Usage."""

        self._enabled = self._available = self._all = None
        self._direct.clear()

    def lookup(self, name: str) -> Service | None:
        """Fetch one service by name, cached; ``None`` when Google has no such service."""

        canonical = canonical_service(name)
        if canonical not in self._direct:
            self._direct[canonical] = get_service(
                self.project,
                self.token,
                canonical,
                quota_project=self._quota_project,
            )
        return self._direct[canonical]

    def resolve(self, name: str) -> Service:
        """Resolve a full or short name to exactly one catalog entry."""

        raw = name.strip()
        canonical = canonical_service(raw)

        # A short or full canonical name resolves with services.get, avoiding
        # the rate-limited listing entirely.
        direct = self.lookup(canonical)
        if direct is not None:
            return direct

        combined = (*self.enabled(), *self.available())
        needle = raw.lower()
        matches = [item for item in combined if _matches(item, needle)]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise AmbiguousService(raw, (item.name for item in matches))

        names = [item.name for item in combined]
        suggestions = difflib.get_close_matches(canonical, names, n=5, cutoff=0.5)
        raise UnknownService(raw, suggestions)

    def enable(self, *names: str, disable_on_destroy: bool = False) -> list[ProjectApi]:
        """Resolve ``names`` and return ``ProjectApi`` entries, order preserved.

        Already-enabled services are returned too: re-declaring an enabled API
        is an OpenTofu no-op, and it keeps the stack the single source of truth.
        """

        seen: set[str] = set()
        apis: list[ProjectApi] = []
        for name in names:
            service = self.resolve(name)
            if service.name in seen:
                continue
            seen.add(service.name)
            apis.append(
                ProjectApi(
                    project=self.project,
                    service=service.name,
                    disable_on_destroy=disable_on_destroy,
                )
            )
        return apis


def enable_apis(
    project: str,
    *names: str,
    credentials: str | None = None,
    quota_project: str | None = None,
    impersonate_service_account: str | None = None,
) -> list[ProjectApi]:
    """One-shot convenience wrapper around :meth:`ServiceCatalog.enable`."""

    return ServiceCatalog(
        project,
        credentials=credentials,
        quota_project=quota_project,
        impersonate_service_account=impersonate_service_account,
    ).enable(*names)


__all__ = [
    "AmbiguousService",
    "DISABLED",
    "ENABLED",
    "Service",
    "ServiceCatalog",
    "ServiceUsageError",
    "UnknownService",
    "canonical_service",
    "enable_apis",
    "get_service",
    "list_services",
]
