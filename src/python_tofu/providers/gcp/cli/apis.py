"""GCP-specific ``apis`` command: inspect and resolve Service Usage entries."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

import typer

from python_tofu.core.cli.base import BaseCommand
from python_tofu.core.cli.options import ConfigOption, VerboseOption, make_context
from python_tofu.core.exceptions import TofuError
from python_tofu.core.provider import Provider
from python_tofu.providers.gcp.services import Service, ServiceCatalog
from python_tofu.providers.gcp.stack import GcpStack


class Mode(str, Enum):
    available = "available"
    enabled = "enabled"
    all = "all"


def _line(service: Service) -> str:
    title = f"  {service.title}" if service.title else ""
    return f"{service.name}{title}  [{service.state.lower()}]"


def create_app(provider: Provider) -> typer.Typer:
    app = typer.Typer(help="List available, enabled or all Google APIs via Service Usage.")

    @app.callback(invoke_without_command=True)
    def apis(
        config: ConfigOption = Path("infra.py"),
        project: str | None = typer.Option(
            None,
            "--project",
            help="Project to inspect; skips loading --config when given.",
        ),
        mode: Mode = typer.Option(
            Mode.available,
            "--state",
            case_sensitive=False,
            help="available (DISABLED), enabled, or all services.",
        ),
        filter_text: str | None = typer.Option(
            None, "--filter", help="Case-insensitive substring match on name or title."
        ),
        quota_project: str | None = typer.Option(
            None,
            "--quota-project",
            help="Send x-goog-user-project for user credentials (ADC).",
        ),
        resolve: str | None = typer.Option(
            None, "--resolve", help="Resolve a short or full API name and print the match."
        ),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
        verbose: VerboseOption = False,
    ) -> None:
        command = BaseCommand(make_context(config, Path(".tofu"), "tofu", verbose, provider))

        if project is not None:
            catalog = ServiceCatalog(project, quota_project=quota_project)
        else:
            stack = command.load()
            if not isinstance(stack, GcpStack):
                command.abort("apis expects a GCP stack")
            catalog = ServiceCatalog(stack.provider.project, credentials=stack.provider.credentials)

        try:
            if resolve is not None:
                service = catalog.resolve(resolve)
                if json_output:
                    typer.echo(json.dumps(service.as_dict()))
                else:
                    typer.echo(_line(service))
                return

            lookup = {
                Mode.available: catalog.available,
                Mode.enabled: catalog.enabled,
                Mode.all: catalog.all,
            }[mode]
            services = lookup(filter_text)
        except TofuError as exc:
            command.abort(str(exc))

        if json_output:
            typer.echo(json.dumps([service.as_dict() for service in services]))
            return
        if not services:
            typer.echo("No services matched.")
            return
        for service in services:
            typer.echo(_line(service))
        typer.echo(f"{len(services)} service(s).")

    return app


__all__ = ["Mode", "create_app"]
