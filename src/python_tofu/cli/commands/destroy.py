"""``python-tofu destroy`` — render and destroy the stack."""

from __future__ import annotations

from pathlib import Path

import typer

from python_tofu.cli.commands.base import BaseCommand
from python_tofu.cli.options import (
    BinaryOption,
    ConfigOption,
    VarFileOption,
    VerboseOption,
    WorkdirOption,
    make_context,
)

app = typer.Typer(help="Render the stack and destroy it with OpenTofu.")


@app.callback(invoke_without_command=True)
def destroy(
    config: ConfigOption = Path("infra.py"),
    workdir: WorkdirOption = Path(".tofu"),
    binary: BinaryOption = "tofu",
    verbose: VerboseOption = False,
    auto_approve: bool = typer.Option(
        False, "--auto-approve", help="Skip the interactive approval."
    ),
    var_file: VarFileOption = None,
) -> None:
    command = BaseCommand(make_context(config, workdir, binary, verbose))
    command.prepare()
    runner = command.runner()
    command.handle(runner.init())
    command.handle(runner.destroy(auto_approve=auto_approve, var_file=var_file))
