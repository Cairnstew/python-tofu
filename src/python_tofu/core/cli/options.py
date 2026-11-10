"""Shared option types and context construction for every command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from python_tofu.core.cli.context import AppContext
from python_tofu.core.limits import LimitMode, UsageMode
from python_tofu.core.provider import Provider

ConfigOption = Annotated[
    Path,
    typer.Option("--config", "-c", help="Python module exposing a module-level `stack`."),
]
WorkdirOption = Annotated[
    Path,
    typer.Option("--workdir", "-w", help="Directory where HCL and state are written."),
]
BinaryOption = Annotated[str, typer.Option("--binary", help="OpenTofu binary to invoke.")]
VerboseOption = Annotated[bool, typer.Option("--verbose", "-v", help="Print every tofu command.")]
VarFileOption = Annotated[
    Path | None,
    typer.Option("--var-file", help="Pass an extra tfvars file to tofu."),
]
LimitModeOption = Annotated[
    LimitMode | None,
    typer.Option(
        "--limits",
        help="Enforce provider limits: error (default), warn, or off.",
    ),
]
UsageModeOption = Annotated[
    UsageMode | None,
    typer.Option(
        "--usage",
        help="Measure declared stack only (stack) or also live infrastructure (live).",
    ),
]
FailOnUnknownOption = Annotated[
    bool,
    typer.Option(
        "--fail-on-unknown",
        help="Fail when a limit could not be measured instead of treating it as unseen.",
    ),
]


def make_context(
    config: Path,
    workdir: Path,
    binary: str,
    verbose: bool,
    provider: Provider,
    limit_mode: LimitMode | None = None,
    usage_mode: UsageMode | None = None,
    fail_on_unknown: bool = False,
) -> AppContext:
    # Typer hands paths through unchanged, so a quoted ``~/...`` keeps its
    # tilde. Expand it here; relative paths stay relative to the caller.
    return AppContext(
        provider=provider,
        config_path=config,
        workdir=workdir.expanduser(),
        binary=binary,
        verbose=verbose,
        limit_mode=limit_mode,
        usage_mode=usage_mode or UsageMode.STACK,
        fail_on_unknown=fail_on_unknown,
    )


def resolve_path(path: Path | None) -> Path | None:
    """Resolve a user-supplied path against the current directory.

    ``tofu`` runs with ``cwd=<workdir>``, so a relative ``--plan-file`` or
    ``--var-file`` would otherwise be looked up inside the workdir instead of
    next to the user. Resolve it up front so paths mean what the shell says.
    """

    return None if path is None else path.expanduser().resolve()
