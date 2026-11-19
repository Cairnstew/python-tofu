"""``quota`` — reconcile the stack's usage-ceiling overrides.

Quota overrides are the one GCP mechanism that stops consumption instead of
reporting it: a budget only emails, while a Service Usage consumer quota
override is enforced by the API. This command is a dry run by default and only
writes with ``--apply``, like ``prune``.
"""

from __future__ import annotations

from pathlib import Path

import typer

from python_tofu.core.cli.base import BaseCommand
from python_tofu.core.cli.options import (
    BinaryOption,
    ConfigOption,
    FailOnUnknownOption,
    StackNameOption,
    UsageModeOption,
    VerboseOption,
    WorkdirOption,
    make_context,
)
from python_tofu.core.limits import LimitMode
from python_tofu.core.provider import Provider


def create_app(provider: Provider) -> typer.Typer:
    app = typer.Typer(
        help="Apply the declared quota overrides (hard usage ceilings). Dry run by default."
    )

    @app.callback(invoke_without_command=True)
    def quota(
        config: ConfigOption = Path("infra.py"),
        workdir: WorkdirOption = None,
        binary: BinaryOption = "tofu",
        verbose: VerboseOption = False,
        usage: UsageModeOption = None,
        fail_on_unknown: FailOnUnknownOption = False,
        stack_name: StackNameOption = None,
        apply_changes: bool = typer.Option(
            False, "--apply", help="Actually create or update the overrides."
        ),
        auto_approve: bool = typer.Option(
            False, "--auto-approve", help="Skip the confirmation prompt."
        ),
    ) -> None:
        command = BaseCommand(
            make_context(
                config,
                workdir,
                binary,
                verbose,
                provider,
                LimitMode.OFF,
                usage,
                fail_on_unknown,
                stack_name=stack_name,
            )
        )
        stack = command.load()
        command.quota(stack, dry_run=not apply_changes, auto_approve=auto_approve)

    return app
