"""``python-tofu apply`` — render and apply the stack."""

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

app = typer.Typer(help="Render the stack and apply it with OpenTofu.")


@app.callback(invoke_without_command=True)
def apply(
    config: ConfigOption = Path("infra.py"),
    workdir: WorkdirOption = Path(".tofu"),
    binary: BinaryOption = "tofu",
    verbose: VerboseOption = False,
    auto_approve: bool = typer.Option(
        False, "--auto-approve", help="Skip the interactive approval."
    ),
    plan_file: Path | None = typer.Option(
        None, "--plan-file", help="Apply a previously saved plan."
    ),
    var_file: VarFileOption = None,
) -> None:
    command = BaseCommand(make_context(config, workdir, binary, verbose))
    runner = command.runner()

    if plan_file is None:
        command.prepare()
        command.handle(runner.init())

    command.handle(runner.apply(auto_approve=auto_approve, plan_file=plan_file, var_file=var_file))
