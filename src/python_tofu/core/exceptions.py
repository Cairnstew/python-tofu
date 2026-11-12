"""Exception hierarchy for python-tofu."""

from __future__ import annotations


class TofuError(Exception):
    """Root exception for every python-tofu error."""


class ConfigError(TofuError):
    """The Python infrastructure module could not be loaded or is invalid."""


class RenderError(TofuError):
    """The stack could not be rendered to valid OpenTofu configuration."""


class PruneError(TofuError):
    """A prune plan could not be adopted or destroyed."""


class TofuNotInstalledError(TofuError):
    """The ``tofu`` binary could not be found."""

    def __init__(self, binary: str) -> None:
        super().__init__(
            f"OpenTofu binary {binary!r} was not found on PATH. "
            "Install OpenTofu or pass --binary /path/to/tofu."
        )
        self.binary = binary


class TofuCommandError(TofuError):
    """An OpenTofu command exited non-zero."""

    def __init__(
        self,
        command: list[str],
        returncode: int,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        message = f"command failed ({returncode}): {' '.join(command)}"
        if stderr.strip():
            message = f"{message}\n{stderr.strip()}"
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
