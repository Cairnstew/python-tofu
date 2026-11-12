"""Modular command registry and entry-point plugin discovery.

Built-in commands register with :data:`DEFAULT_COMMANDS`; the CLI renders
whatever the registry contains. Out-of-tree packages can contribute without
importing CLI internals by declaring setuptools entry points::

    [project.entry-points."python_tofu.providers"]
    acme = "acme_tofu:PROVIDER"

    [project.entry-points."python_tofu.commands"]
    acme = "acme_tofu.commands:SPECS"

A provider entry point resolves to a :class:`~python_tofu.core.provider.Provider`
(or a zero-argument callable returning one); a command entry point resolves to a
:class:`CommandSpec` or an iterable of them.

Discovery is best-effort: a broken plugin is reported in :class:`PluginReport`
and never stops the CLI from starting.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import metadata
from typing import Callable, Iterable

import typer

from python_tofu.core.exceptions import TofuError
from python_tofu.core.provider import Provider, register_provider

CommandFactory = Callable[[Provider], typer.Typer]

PROVIDER_GROUP = "python_tofu.providers"
COMMAND_GROUP = "python_tofu.commands"

#: Set to ``1``/``true``/``yes``/``on`` to skip entry-point discovery.
PLUGIN_ENV = "PYTHON_TOFU_NO_PLUGINS"


@dataclass(frozen=True)
class CommandSpec:
    """One CLI sub-application and how it is displayed."""

    name: str
    factory: CommandFactory
    aliases: tuple[str, ...] = ()
    help: str = ""
    order: int = 100

    def __post_init__(self) -> None:
        if not self.name or self.name.startswith("-") or "/" in self.name:
            raise ValueError(f"invalid command name: {self.name!r}")
        if any(character.isspace() for character in self.name):
            raise ValueError(f"command name must not contain whitespace: {self.name!r}")


@dataclass(frozen=True)
class PluginReport:
    """What discovery loaded, and what it could not load."""

    providers: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.providers or self.commands or self.errors)


class CommandRegistry:
    """Ordered collection of command specs, keyed by primary name."""

    def __init__(self) -> None:
        self._specs: dict[str, CommandSpec] = {}
        self.last_report: PluginReport | None = None

    def register(
        self,
        name: str,
        factory: CommandFactory,
        *,
        aliases: Iterable[str] = (),
        help: str = "",
        order: int = 100,
        replace: bool = False,
    ) -> CommandSpec:
        """Register ``factory`` as ``name``; re-registering the same factory is a no-op."""

        spec = CommandSpec(name, factory, tuple(aliases), help, order)
        existing = self._specs.get(name)
        if existing is not None and existing.factory is factory:
            return existing
        if existing is not None and not replace:
            raise TofuError(f"command {name!r} is already registered")

        taken = self._taken_names()
        if existing is not None:
            taken.pop(name, None)
            for alias in existing.aliases:
                taken.pop(alias, None)
        for alias in spec.aliases:
            if alias == name:
                raise TofuError(f"command {name!r} cannot alias itself")
            if alias in taken:
                raise TofuError(f"command alias {alias!r} is already registered")

        self._specs[name] = spec
        return spec

    def register_spec(self, spec: CommandSpec, *, replace: bool = False) -> CommandSpec:
        return self.register(
            spec.name,
            spec.factory,
            aliases=spec.aliases,
            help=spec.help,
            order=spec.order,
            replace=replace,
        )

    def get(self, name: str) -> CommandSpec:
        try:
            return self._specs[name]
        except KeyError:
            known = ", ".join(self.names()) or "none"
            raise TofuError(f"unknown command {name!r} (registered: {known})") from None

    def specs(self) -> tuple[CommandSpec, ...]:
        """Commands in display order (stable for equal ``order`` values)."""

        return tuple(sorted(self._specs.values(), key=lambda spec: spec.order))

    def names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.specs())

    def pairs(self) -> tuple[tuple[str, CommandFactory], ...]:
        """Backwards-compatible ``(name, factory)`` form."""

        return tuple((spec.name, spec.factory) for spec in self.specs())

    def _taken_names(self) -> dict[str, CommandFactory]:
        taken: dict[str, CommandFactory] = {}
        for spec in self._specs.values():
            taken[spec.name] = spec.factory
            for alias in spec.aliases:
                taken[alias] = spec.factory
        return taken


DEFAULT_COMMANDS = CommandRegistry()


def register_command(
    name: str,
    *,
    aliases: Iterable[str] = (),
    help: str = "",
    order: int = 100,
) -> Callable[[CommandFactory], CommandFactory]:
    """Decorator that registers a ``create_app(provider)`` factory in-tree."""

    def decorator(factory: CommandFactory) -> CommandFactory:
        DEFAULT_COMMANDS.register(name, factory, aliases=aliases, help=help, order=order)
        return factory

    return decorator


def _entry_points(group: str) -> Iterable[metadata.EntryPoint]:
    return metadata.entry_points(group=group)


def plugins_disabled() -> bool:
    return os.environ.get(PLUGIN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def discover_plugins(registry: CommandRegistry | None = None) -> PluginReport:
    """Load entry points, register what works and report what does not."""

    target = DEFAULT_COMMANDS if registry is None else registry
    providers: list[str] = []
    commands: list[str] = []
    errors: list[str] = []

    for entry_point in _entry_points(PROVIDER_GROUP):
        try:
            loaded = entry_point.load()
            provider = loaded() if not isinstance(loaded, Provider) and callable(loaded) else loaded
            if not isinstance(provider, Provider):
                raise TypeError(f"expected Provider, got {type(loaded).__name__}")
            register_provider(provider)
            if provider.name not in providers:
                providers.append(provider.name)
        except Exception as exc:  # noqa: BLE001 - a plugin must not break the CLI
            errors.append(f"provider {entry_point.name!r}: {exc}")

    for entry_point in _entry_points(COMMAND_GROUP):
        try:
            loaded = entry_point.load()
            if isinstance(loaded, CommandSpec):
                specs = (loaded,)
            else:
                try:
                    specs = tuple(loaded)
                except TypeError:
                    raise TypeError(
                        "expected CommandSpec or an iterable of CommandSpec, "
                        f"got {type(loaded).__name__}"
                    ) from None
            if not specs or not all(isinstance(spec, CommandSpec) for spec in specs):
                raise TypeError("expected CommandSpec or an iterable of CommandSpec")
            for spec in specs:
                target.register_spec(spec)
                if spec.name not in commands:
                    commands.append(spec.name)
        except Exception as exc:  # noqa: BLE001 - a plugin must not break the CLI
            errors.append(f"command {entry_point.name!r}: {exc}")

    report = PluginReport(tuple(providers), tuple(commands), tuple(errors))
    target.last_report = report
    return report


__all__ = [
    "COMMAND_GROUP",
    "DEFAULT_COMMANDS",
    "PLUGIN_ENV",
    "PROVIDER_GROUP",
    "CommandFactory",
    "CommandRegistry",
    "CommandSpec",
    "PluginReport",
    "discover_plugins",
    "plugins_disabled",
    "register_command",
]
