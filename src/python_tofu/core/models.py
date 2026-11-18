"""Provider-agnostic model primitives.

Providers subclass :class:`BaseStack` to add their own provider settings and
resource collections. Everything here must stay usable by any OpenTofu
provider.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from python_tofu.core.limits import LimitMode


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


#: Sentinel section meaning "every section the provider can prune".
ALL_SECTIONS = "all"

#: Output names become HCL identifiers, so they follow the same grammar.
_OUTPUT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

#: Stack names become directory names and state prefixes.
_STACK_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_stack_name(value: str) -> str:
    """Return ``value`` if it is safe as a workdir component and state prefix."""

    if not _STACK_NAME.match(value):
        raise ValueError(
            f"stack name {value!r} must start alphanumeric and contain only "
            "letters, digits, dots, dashes and underscores"
        )
    return value


class Output(TofuModel):
    """A value OpenTofu exposes after apply: ``output "name" { value = ... }``.

    ``value`` is rendered like any other attribute, so plain Python values
    become literals and :func:`python_tofu.hcl.ref` carries a resource
    reference. Outputs render after every resource, so results such as a
    service URL or bucket name can be read back with ``python-tofu output``.
    """

    name: str
    value: Any
    description: str | None = None
    sensitive: bool = False

    def __init__(
        self,
        name: str,
        value: Any,
        description: str | None = None,
        sensitive: bool = False,
        **data: Any,
    ) -> None:
        # Accept the documented positional form as well as keywords; Pydantic
        # models are keyword-only by default.
        fields: dict[str, Any] = {
            "name": name,
            "value": value,
            "description": description,
            "sensitive": sensitive,
        }
        fields.update(data)
        super().__init__(**fields)

    @field_validator("name")
    @classmethod
    def _name_is_an_hcl_identifier(cls, value: str) -> str:
        if not _OUTPUT_NAME.match(value):
            raise ValueError(
                f"output name {value!r} is not an HCL identifier "
                "(letters, digits, underscores and dashes; cannot start with a digit)"
            )
        return value

    @field_validator("description")
    @classmethod
    def _description_is_single_line(cls, value: str | None) -> str | None:
        if value is not None and ("\n" in value or "\r" in value):
            raise ValueError("output description must be a single line")
        return value


class PruneConfig(TofuModel):
    """Opt-in deletion of live resources the stack does not declare.

    Off by default. Set ``enabled=True`` to make the selected sections
    authoritative; ``sections=("all",)`` covers every section the provider
    supports. Service accounts are excluded from ``all`` and require a second,
    explicit gate (``include_service_accounts=True`` plus the CLI's
    ``--allow-service-accounts``) because deleting the identity that runs the
    tool is irreversible. Project deletion is likewise never implied by
    ``all``; it must be named explicitly. Providers validate section names
    against their own list.
    """

    enabled: bool = False
    sections: tuple[str, ...] = (ALL_SECTIONS,)
    include_service_accounts: bool = False
    allow_raw_hcl: bool = Field(
        default=False,
        description=(
            "Allow pruning when the stack also uses `extra_files`. Raw HCL is "
            "invisible to discovery, so resources declared there look undeclared "
            "and would be deleted. Off by default."
        ),
    )
    protected_service_accounts: tuple[str, ...] = Field(
        default_factory=tuple,
        description=(
            "Service account ids or emails that prune must never delete, on top "
            "of the active credential's own identity."
        ),
    )
    protected_iam_roles: tuple[str, ...] = Field(
        default=("roles/owner",),
        description=(
            "IAM roles prune must never remove. roles/owner is always included, "
            "even when this tuple is empty."
        ),
    )
    protected_projects: tuple[str, ...] = Field(
        default_factory=tuple,
        description=(
            "Project ids that prune must never delete, on top of the provider "
            "project, declared and external projects, and the project that owns "
            "the active credential."
        ),
    )

    @field_validator("protected_iam_roles")
    @classmethod
    def _owner_is_always_protected(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(dict.fromkeys(item.strip() for item in value))
        if any(not item for item in cleaned):
            raise ValueError("protected_iam_roles entries must not be empty")
        owner = "roles/owner"
        return cleaned if owner in cleaned else (owner, *cleaned)

    @field_validator("protected_service_accounts")
    @classmethod
    def _protected_accounts_are_clean(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value)
        if any(not item for item in cleaned):
            raise ValueError("protected_service_accounts entries must not be empty")
        duplicates = sorted({item for item in cleaned if cleaned.count(item) > 1})
        if duplicates:
            raise ValueError(
                "duplicate protected_service_accounts entries: " + ", ".join(duplicates)
            )
        return cleaned

    @field_validator("protected_projects")
    @classmethod
    def _protected_projects_are_clean(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(dict.fromkeys(item.strip() for item in value))
        if any(not item for item in cleaned):
            raise ValueError("protected_projects entries must not be empty")
        return cleaned

    @field_validator("sections")
    @classmethod
    def _sections_are_known_shape(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("prune sections must not be empty")
        if ALL_SECTIONS in value and len(value) > 1:
            raise ValueError(f"prune section {ALL_SECTIONS!r} cannot be combined with others")
        duplicates = sorted({item for item in value if value.count(item) > 1})
        if duplicates:
            raise ValueError("duplicate prune sections: " + ", ".join(duplicates))
        return value

    def resolve(
        self, supported: tuple[str, ...], explicit_only: tuple[str, ...] = ()
    ) -> tuple[str, ...]:
        """Return the concrete section names selected by this config.

        ``explicit_only`` sections are validated but never implied by ``all``;
        they must be named explicitly. This keeps destructive optional sweeps
        (project IAM) out of existing ``all`` stacks.
        """

        if ALL_SECTIONS in self.sections:
            wanted = tuple(item for item in supported if item not in explicit_only)
        else:
            wanted = self.sections
        unknown = sorted(set(wanted) - set(supported))
        if unknown:
            raise ValueError(
                "unsupported prune section(s): "
                + ", ".join(unknown)
                + ". Supported: "
                + ", ".join(supported)
            )
        return tuple(item for item in supported if item in wanted)


class BaseStack(TofuModel):
    """Minimal stack envelope shared by every provider.

    Provider stacks add their ``provider`` object, resource lists and whatever
    validation their resources need. ``backend`` is intentionally untyped here
    so each provider can declare its own backend model.
    """

    required_version: str = ">= 1.6.0"
    backend: Any = None
    name: str | None = Field(
        default=None,
        description=(
            "Stack name used for the default state prefix and workdir "
            "(`.tofu/<name>`). Defaults to the config file stem; the CLI's "
            "`--stack-name` overrides it."
        ),
    )
    outputs: list[Output] = Field(
        default_factory=list,
        description=(
            "Values exposed after apply (`output` blocks). Use "
            '`python_tofu.ref("resource.type.name.attr")` for references.'
        ),
    )
    prune: PruneConfig = Field(default_factory=PruneConfig)
    limits_mode: LimitMode | None = Field(
        default=None,
        description=(
            "Stack-level limit enforcement, used when neither `--limits` nor the "
            "provider policy chooses one. Profiles such as `preview` set `warn`."
        ),
    )
    extra_files: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Extra ``.tf``/``.tf.json`` files written verbatim into the workdir. "
            "An escape hatch for provider resources the DSL does not model yet; "
            "managed files (versions.tf, providers.tf, main.tf, .gitignore) win."
        ),
    )

    @field_validator("name")
    @classmethod
    def _name_is_path_safe(cls, value: str | None) -> str | None:
        if value is not None:
            validate_stack_name(value)
        return value

    @model_validator(mode="after")
    def _output_names_are_unique(self) -> "BaseStack":
        names = [item.name for item in self.outputs]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError("duplicate output names: " + ", ".join(duplicates))
        return self
