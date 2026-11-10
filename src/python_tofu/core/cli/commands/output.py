"""``output`` — read OpenTofu outputs."""

from __future__ import annotations

from pathlib import Path

import typer

from python_tofu.core.cli.base import BaseCommand
from python_tofu.core.cli.options import (
    BinaryOption,
    VerboseOption,
    WorkdirOption,
    make_context,
)
from python_tofu.core.provider import Provider


def create_app(provider: Provider) -> typer.Typer:
    app = typer.Typer(help="Read outputs from the OpenTofu working directory.")

    @app.callback(invoke_without_command=True)
    def output(
        workdir: WorkdirOption = Path(".tofu"),
        binary: BinaryOption = "tofu",
        verbose: VerboseOption = False,
        json_output: bool = typer.Option(
            True, "--json/--no-json", help="Emit machine-readable JSON."
        ),
    ) -> None:
        command = BaseCommand(make_context(Path("infra.py"), workdir, binary, verbose, provider))
        if not command.ctx.workdir.exists():
            command.abort(f"working directory does not exist: {command.ctx.workdir}")
        command.run_tofu("output", json_output=json_output)

    return app
