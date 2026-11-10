"""Provider-agnostic model primitives.

Providers subclass :class:`BaseStack` to add their own provider settings and
resource collections. Everything here must stay usable by any OpenTofu
provider.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TofuModel(BaseModel):
    """Strict, immutable base model for all infrastructure objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class BackendConfig(TofuModel):
    """Generic state backend: a kind plus free-form settings.

    Providers whose backend has typed fields (for example GCS ``bucket`` and
    ``prefix``) define their own model and render the block themselves.
    """

    kind: str
    settings: dict[str, Any] = Field(default_factory=dict)


class BaseStack(TofuModel):
    """Minimal stack envelope shared by every provider.

    Provider stacks add their ``provider`` object, resource lists and whatever
    validation their resources need. ``backend`` is intentionally untyped here
    so each provider can declare its own backend model.
    """

    required_version: str = ">= 1.6.0"
    backend: Any = None
