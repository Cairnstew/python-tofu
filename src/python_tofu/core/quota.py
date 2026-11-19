"""Provider-agnostic reconciliation of hard usage ceilings (quota overrides).

Provider limits (see :mod:`python_tofu.core.limits`) are enforced by the wrapper
*before* it calls ``tofu``: they refuse to plan something that measures above a
ceiling. Some ceilings, however, can also be enforced by the cloud itself —
GCP Service Usage consumer quota overrides are the motivating case, because
they cap what a project can consume no matter who applies what. That is the
only mechanism that makes a spend limit hard rather than an alert.

A provider reports declared overrides and their live values as a
:class:`QuotaPlan`. Discovery is read-only, so the ``quota`` command is a dry
run by default and only writes with ``--apply`` — the same shape as ``prune``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuotaChange:
    """One override that is absent or carries a different value than declared.

    ``handle`` is provider-opaque: core only prints ``address``/``current``/
    ``desired`` and hands the object back to ``Provider.apply_quota``.
    """

    action: str
    address: str
    desired: str
    current: str | None = None
    handle: str = ""
    force: bool = True

    @property
    def is_create(self) -> bool:
        return self.action == "create"


@dataclass(frozen=True)
class QuotaPlan:
    """Overrides to create or update, plus non-fatal discovery notes."""

    changes: tuple[QuotaChange, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.changes


__all__ = ["QuotaChange", "QuotaPlan"]
