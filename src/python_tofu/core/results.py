"""Result value objects shared by services and the CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RenderResult:
    """Outcome of rendering a stack to disk."""

    workdir: Path
    files: tuple[Path, ...]
    resources: int


@dataclass(frozen=True)
class PlanSummary:
    """Counts derived from ``tofu show -json``."""

    create: int = 0
    update: int = 0
    delete: int = 0
    replace: int = 0
    no_op: int = 0
    other: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(self.create or self.update or self.delete or self.replace or self.other)

    @property
    def total(self) -> int:
        return self.create + self.update + self.delete + self.replace + self.no_op + self.other

    @classmethod
    def from_show_json(cls, payload: dict[str, Any]) -> "PlanSummary":
        counts = {"create": 0, "update": 0, "delete": 0, "replace": 0, "no_op": 0, "other": 0}
        for change in payload.get("resource_changes", []):
            actions = change.get("change", {}).get("actions", [])
            if actions == ["create"]:
                counts["create"] += 1
            elif actions == ["update"]:
                counts["update"] += 1
            elif actions == ["delete"]:
                counts["delete"] += 1
            elif "create" in actions and "delete" in actions:
                counts["replace"] += 1
            elif actions == ["no-op"]:
                counts["no_op"] += 1
            else:
                counts["other"] += 1
        return cls(**counts)

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "create": self.create,
            "update": self.update,
            "delete": self.delete,
            "replace": self.replace,
            "no_op": self.no_op,
            "other": self.other,
            "has_changes": self.has_changes,
        }


@dataclass(frozen=True)
class CommandResult:
    """Captured result of an OpenTofu subprocess."""

    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def command(self) -> list[str]:
        return list(self.args)
