"""Build the Typer application for a provider."""

from __future__ import annotations

import typer

from python_tofu.core.cli.commands import COMMANDS
from python_tofu.core.cli.registry import (
    DEFAULT_COMMANDS,
    CommandRegistry,
    discover_plugins,
    plugins_disabled,
)
from python_tofu.core.provider import Provider


def build_app(
    provider: Provider,
    *,
    version: str,
    name: str = "python-tofu",
    commands: CommandRegistry | None = None,
    plugins: bool | None = None,
) -> typer.Typer:
    """Return a Typer app whose commands render ``provider`` stacks.

    ``commands`` defaults to the process-wide registry (which already holds the
    built-ins). ``plugins`` defaults to "on unless ``PYTHON_TOFU_NO_PLUGINS`` is
    set"; pass ``False`` for a deterministic app with no entry-point discovery.
    """

    registry = DEFAULT_COMMANDS if commands is None else commands
    if plugins is None:
        plugins = not plugins_disabled()
    if plugins:
        report = discover_plugins(registry)
        for error in report.errors:
            typer.secho(f"Warning: plugin {error}", fg=typer.colors.YELLOW, err=True)

    app = typer.Typer(
        name=name,
        no_args_is_help=True,
        help=f"Manage {provider.label} infrastructure with a typed Python DSL and OpenTofu.",
    )

    def _show_version(value: bool) -> None:
        if value:
            typer.echo(f"{name} {version}")
            raise typer.Exit()

    @app.callback()
    def main(
        version_option: bool = typer.Option(
            False,
            "--version",
            callback=_show_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ) -> None:
        """Manage infrastructure with a typed Python DSL and OpenTofu."""

    for spec in registry.specs():
        sub_app = spec.factory(provider)
        if spec.help:
            app.add_typer(sub_app, name=spec.name, help=spec.help)
        else:
            app.add_typer(sub_app, name=spec.name)
        for alias in spec.aliases:
            app.add_typer(spec.factory(provider), name=alias, hidden=True)

    return app


__all__ = ["COMMANDS", "build_app"]
