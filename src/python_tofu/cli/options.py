"""Shared option types and context construction for every command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from python_tofu.cli.context import AppContext

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


def make_context(
    config: Path,
    workdir: Path,
    binary: str,
    verbose: bool,
) -> AppContext:
    return AppContext(config_path=config, workdir=workdir, binary=binary, verbose=verbose)
