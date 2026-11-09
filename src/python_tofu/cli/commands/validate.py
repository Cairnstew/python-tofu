"""``python-tofu validate`` — render, init and validate the configuration."""

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

app = typer.Typer(help="Render, initialise and validate the OpenTofu configuration.")


@app.callback(invoke_without_command=True)
def validate(
    config: ConfigOption = Path("infra.py"),
    workdir: WorkdirOption = Path(".tofu"),
    binary: BinaryOption = "tofu",
    verbose: VerboseOption = False,
) -> None:
    command = BaseCommand(make_context(config, workdir, binary, verbose))
    command.prepare()
    runner = command.runner()
    command.handle(runner.init())
    command.handle(runner.validate())
