"""Evaluate a Nix-authored stack file into plain JSON data.

Nix is an *authoring* front-end only: it produces the same mapping the Python
DSL produces, and the provider's Pydantic models still validate and render it.
No HCL is generated here.

The accepted file shapes are deliberately small:

* an attribute set in the ``GcpStack`` schema (or ``{ stack = ...; }``);
* a function whose arguments all have defaults, e.g. ``{ pkgs ? ... }: ...``.

``--apply`` calls a function with an empty argument set, so a plain attribute
set is returned unchanged.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 - evaluating the user's own Nix file is the feature
from pathlib import Path
from typing import Any

from python_tofu.core.exceptions import ConfigError

#: Set to a Nix binary path to override ``nix`` discovery.
NIX_ENV = "PYTHON_TOFU_NIX"
#: Set to ``1`` to force ``--impure`` (needed for ``builtins.getFlake``).
NIX_IMPURE_ENV = "PYTHON_TOFU_NIX_IMPURE"

_CALL_FUNCTION = "x: if builtins.isFunction x then x { } else x"

#: Tokens that make a pure evaluation fail. A config that uses them is evaluated
#: with ``--impure`` (the same escape hatch ``nix eval --impure`` provides).
_IMPURE_MARKERS = ("<nixpkgs>", "<nixos-config>", "builtins.getFlake", "builtins.currentSystem")


def _nix_binary() -> str:
    configured = os.environ.get(NIX_ENV)
    if configured:
        return configured
    found = shutil.which("nix")
    if found is None:
        raise ConfigError(
            "this config is a .nix file but the `nix` binary was not found on PATH. "
            f"Install Nix or set ${NIX_ENV} to its path."
        )
    return found


def _needs_impure(path: Path) -> bool:
    if os.environ.get(NIX_IMPURE_ENV) == "1":
        return True
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return any(marker in text for marker in _IMPURE_MARKERS)


def nix_eval_command(path: Path, *, impure: bool | None = None) -> list[str]:
    """Build the argv used to evaluate ``path`` (exposed for ``doctor``/tests)."""

    command = [_nix_binary(), "eval", "--json", "--file", str(path), "--apply", _CALL_FUNCTION]
    if impure is None:
        impure = _needs_impure(path)
    if impure:
        command.insert(2, "--impure")
    return command


def eval_nix_json(path: str | Path) -> Any:
    """Return the JSON value produced by the Nix expression in ``path``."""

    resolved = Path(path).expanduser().resolve()
    command = nix_eval_command(resolved)
    try:
        # argv list, no shell; ``nix`` evaluates the user's own config file.
        process = subprocess.run(  # nosec B603
            command,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ConfigError(
            f"cannot evaluate {resolved}: Nix binary {command[0]!r} was not found"
        ) from exc

    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "nix eval failed").strip()
        raise ConfigError(f"cannot evaluate {resolved} with Nix:\n{detail}")

    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"nix eval for {resolved} did not produce JSON: {process.stdout.strip()[:400]}"
        ) from exc
