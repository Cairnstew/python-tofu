"""``output`` — read OpenTofu outputs."""

from __future__ import annotations

from pathlib import Path

import typer

from python_tofu.core.cli.base import BaseCommand
from python_tofu.core.cli.options import (
    BinaryOption,
    ConfigOption,
    StackNameOption,
    VerboseOption,
    WorkdirOption,
    make_context,
)
from python_tofu.core.provider import Provider


def create_app(provider: Provider) -> typer.Typer:
    app = typer.Typer(help="Read outputs from the OpenTofu working directory.")

    @app.callback(invoke_without_command=True)
    def output(
        config: ConfigOption = Path("infra.py"),
        workdir: WorkdirOption = None,
        binary: BinaryOption = "tofu",
        verbose: VerboseOption = False,
        stack_name: StackNameOption = None,
        json_output: bool = typer.Option(
            True, "--json/--no-json", help="Emit machine-readable JSON."
        ),
    ) -> None:
        # ``output`` never renders, but it imports the config when no explicit
        # ``--workdir``/``--stack-name`` is given so a stack's own ``name``
        # selects the same default directory every rendering command uses.
        command = BaseCommand(
            make_context(
                config,
                workdir,
                binary,
                verbose,
                provider,
                stack_name=stack_name,
            )
        )
        command.ctx.workdir = command.ctx.derive_workdir(discover_name=True)
        if not command.ctx.workdir.exists():
            command.abort(
                f"working directory does not exist: {command.ctx.workdir} "
                "(pass --workdir or --stack-name if the stack uses another name)"
            )
        command.run_tofu("output", json_output=json_output)

    return app
