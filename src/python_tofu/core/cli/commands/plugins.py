"""``plugins`` — show the active provider, commands and discovered plugins."""

from __future__ import annotations

import json

import typer

from python_tofu.core.cli.registry import DEFAULT_COMMANDS, PluginReport, discover_plugins
from python_tofu.core.provider import Provider, available_providers


def _report() -> PluginReport:
    report = DEFAULT_COMMANDS.last_report
    return discover_plugins(DEFAULT_COMMANDS) if report is None else report


def create_app(provider: Provider) -> typer.Typer:
    app = typer.Typer(help="Show commands, providers and plugins the CLI discovered.")

    @app.callback(invoke_without_command=True)
    def plugins(
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    ) -> None:
        report = _report()
        command_names = list(DEFAULT_COMMANDS.names())
        provider_names = list(available_providers())
        payload = {
            "active_provider": provider.name,
            "commands": command_names,
            "providers": provider_names,
            "plugins": {
                "providers": list(report.providers),
                "commands": list(report.commands),
            },
            "errors": list(report.errors),
        }

        if json_output:
            typer.echo(json.dumps(payload))
            return

        typer.echo(f"Active provider: {provider.label} ({provider.name})")
        typer.echo("Commands:     " + ", ".join(command_names))
        typer.echo("Providers:    " + ", ".join(provider_names))
        if report.providers or report.commands:
            loaded = ", ".join((*report.providers, *report.commands))
            typer.echo("Plugins:      " + loaded)
        else:
            typer.echo("Plugins:      none discovered")

        for error in report.errors:
            typer.secho(f"Warning: {error}", fg=typer.colors.YELLOW, err=True)

    return app


__all__ = ["create_app"]
