"""``limits`` — show the provider's limits and measured usage."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from python_tofu.core.cli.base import BaseCommand, format_limit
from python_tofu.core.cli.options import (
    ConfigOption,
    FailOnUnknownOption,
    UsageModeOption,
    VerboseOption,
    make_context,
)
from python_tofu.core.limits import LimitMode, LimitUnknown
from python_tofu.core.provider import Provider


def create_app(provider: Provider) -> typer.Typer:
    app = typer.Typer(help="Show provider limits and the usage the stack measures.")

    @app.callback(invoke_without_command=True)
    def limits(
        config: ConfigOption = Path("infra.py"),
        verbose: VerboseOption = False,
        usage: UsageModeOption = None,
        fail_on_unknown: FailOnUnknownOption = False,
        show_all: bool = typer.Option(
            False, "--all", help="Show every limit, including unused and unknown ones."
        ),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    ) -> None:
        command = BaseCommand(
            make_context(
                config,
                Path(".tofu"),
                "tofu",
                verbose,
                provider,
                LimitMode.OFF,
                usage,
                fail_on_unknown,
            )
        )
        stack = command.load()
        report = command.limit_report(stack)
        if report is None:
            command.abort(f"provider {provider.name!r} has no limit policy")

        if json_output:
            typer.echo(json.dumps(report.as_dict()))
            if fail_on_unknown and report.unknown:
                raise typer.Exit(1)
            return

        typer.echo(f"{provider.label} limits: {report.summary()}")
        checks = report.checks if show_all else report.used_checks
        for check in checks:
            if not check.observed:
                marker = "?"
            elif check.exceeded:
                marker = "!"
            else:
                marker = " "
            typer.echo(f"{marker} {format_limit(check)}")

        if report.unknown and not show_all:
            typer.echo(
                f"  ({len(report.unknown)} limits unknown; use --all to list them, "
                "--usage live to measure infrastructure)"
            )
        if fail_on_unknown and report.unknown:
            typer.secho(f"Error: {LimitUnknown(report)}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1)

    return app
