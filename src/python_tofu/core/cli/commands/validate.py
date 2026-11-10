"""``validate`` — render, init and validate the configuration."""

from __future__ import annotations

from pathlib import Path

import typer

from python_tofu.core.cli.base import BaseCommand
from python_tofu.core.cli.options import (
    BinaryOption,
    ConfigOption,
    FailOnUnknownOption,
    LimitModeOption,
    UsageModeOption,
    VerboseOption,
    WorkdirOption,
    make_context,
)
from python_tofu.core.provider import Provider


def create_app(provider: Provider) -> typer.Typer:
    app = typer.Typer(help="Render, initialise and validate the OpenTofu configuration.")

    @app.callback(invoke_without_command=True)
    def validate(
        config: ConfigOption = Path("infra.py"),
        workdir: WorkdirOption = Path(".tofu"),
        binary: BinaryOption = "tofu",
        verbose: VerboseOption = False,
        limits: LimitModeOption = None,
        usage: UsageModeOption = None,
        fail_on_unknown: FailOnUnknownOption = False,
    ) -> None:
        command = BaseCommand(
            make_context(
                config,
                workdir,
                binary,
                verbose,
                provider,
                limits,
                usage,
                fail_on_unknown,
            )
        )
        command.prepare()
        command.run_tofu("init")
        command.run_tofu("validate")

    return app
