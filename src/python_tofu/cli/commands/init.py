"""``python-tofu init`` — render then run ``tofu init``."""

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

app = typer.Typer(help="Render the stack and initialise the OpenTofu working directory.")


@app.callback(invoke_without_command=True)
def init(
    config: ConfigOption = Path("infra.py"),
    workdir: WorkdirOption = Path(".tofu"),
    binary: BinaryOption = "tofu",
    verbose: VerboseOption = False,
    upgrade: bool = typer.Option(
        False,
        "--upgrade",
        help="Reinstall providers to the newest allowed version.",
    ),
) -> None:
    command = BaseCommand(make_context(config, workdir, binary, verbose))
    command.prepare()
    command.handle(command.runner().init(upgrade=upgrade))
