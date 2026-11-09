"""``python-tofu render`` — write HCL without invoking OpenTofu."""

from __future__ import annotations

from pathlib import Path

import typer

from python_tofu.cli.commands.base import BaseCommand
from python_tofu.cli.options import (
    BinaryOption,
    ConfigOption,
    VerboseOption,
    WorkdirOption,
    make_context,
)

app = typer.Typer(help="Render the Python stack to OpenTofu HCL.")


@app.callback(invoke_without_command=True)
def render(
    config: ConfigOption = Path("infra.py"),
    workdir: WorkdirOption = Path(".tofu"),
    binary: BinaryOption = "tofu",
    verbose: VerboseOption = False,
) -> None:
    command = BaseCommand(make_context(config, workdir, binary, verbose))
    _, result = command.prepare()
    typer.echo(f"Rendered {result.resources} resources into {result.workdir}")
    for path in result.files:
        typer.echo(f"  {path}")
