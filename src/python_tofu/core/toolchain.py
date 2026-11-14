"""Toolchain preflight checks for ``python-tofu doctor``.

The provider checks answer "is the cloud ready?". These answer "is the local
toolchain ready?" — the OpenTofu binary and the constraint the stack renders,
the provider mirror/cache the Nix build provides, and the working directory.
Nothing here touches the network or mutates the filesystem.
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404 - probing the user's own tofu binary is the point
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from python_tofu.core.doctor import CheckResult, CheckStatus

_VERSION = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?$")
_CLAUSE = re.compile(r"^(>=|<=|>|<|==|=|~>)?\s*(\d+(?:\.\d+){0,2})$")
_REGISTRY = "registry.opentofu.org"

BINARY_FIX = "install OpenTofu, or pass --binary / set PYTHON_TOFU_BINARY"


@dataclass(frozen=True)
class Constraint:
    """One clause of a Terraform-style version constraint."""

    operator: str
    version: tuple[int, ...]


def parse_version(text: str) -> tuple[int, ...] | None:
    """Parse ``1``, ``1.6`` or ``1.6.0``; return None for anything else."""

    match = _VERSION.match(text.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def parse_constraints(text: str) -> tuple[Constraint, ...] | None:
    """Parse ``>= 1.6.0`` or ``>= 1.6, < 2.0``; None when unsupported."""

    clauses = [clause.strip() for clause in text.split(",") if clause.strip()]
    if not clauses:
        return None
    parsed: list[Constraint] = []
    for clause in clauses:
        match = _CLAUSE.match(clause)
        if match is None:
            return None
        version = parse_version(match.group(2))
        if version is None:
            return None
        parsed.append(Constraint(match.group(1) or "=", version))
    return tuple(parsed)


def _pad(version: tuple[int, ...], width: int) -> tuple[int, ...]:
    return version + (0,) * (width - len(version))


def _matches(version: tuple[int, ...], constraint: Constraint) -> bool:
    target = constraint.version
    width = max(len(version), len(target))
    actual = _pad(version, width)
    wanted = _pad(target, width)

    if constraint.operator in ("=", "=="):
        return actual == wanted
    if constraint.operator == ">=":
        return actual >= wanted
    if constraint.operator == ">":
        return actual > wanted
    if constraint.operator == "<=":
        return actual <= wanted
    if constraint.operator == "<":
        return actual < wanted

    # `~> 7.0` allows 7.x; `~> 7.0.5` allows 7.0.x.
    if actual < wanted:
        return False
    if len(target) <= 2:
        return actual[0] == target[0]
    return actual[:2] == target[:2]


def satisfies(version: str, constraints: Sequence[Constraint]) -> bool | None:
    """Return whether ``version`` satisfies every clause, or None if unparseable."""

    parsed = parse_version(version)
    if parsed is None:
        return None
    return all(_matches(parsed, constraint) for constraint in constraints)


def tofu_version(binary: str) -> tuple[str | None, str]:
    """Return ``(version, detail)`` for ``binary``; version is None on failure."""

    try:
        process = subprocess.run(  # nosec B603 - argv list, no shell
            [binary, "version", "-json"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None, "not found"
    except OSError as exc:
        return None, str(exc)

    if process.returncode == 0:
        try:
            payload = json.loads(process.stdout or "{}")
        except ValueError:
            payload = {}
        reported = payload.get("terraform_version") or payload.get("tofu_version")
        if isinstance(reported, str):
            return reported, ""

    combined = f"{process.stdout}\n{process.stderr}"
    match = re.search(r"v?(\d+\.\d+\.\d+)", combined)
    if match is not None:
        return match.group(1), ""
    detail = (process.stderr or process.stdout).strip()
    return None, detail or f"exit code {process.returncode}"


def check_binary(binary: str, required_version: str) -> CheckResult:
    """Check that the binary exists and satisfies the stack's constraint."""

    version, detail = tofu_version(binary)
    if version is None:
        return CheckResult("tofu", CheckStatus.FAIL, f"{binary}: {detail}", fix=BINARY_FIX)

    constraints = parse_constraints(required_version)
    if constraints is None:
        return CheckResult(
            "tofu",
            CheckStatus.UNKNOWN,
            f"{version}; cannot parse required_version {required_version!r}",
        )

    verdict = satisfies(version, constraints)
    if verdict is None:
        return CheckResult(
            "tofu",
            CheckStatus.UNKNOWN,
            f"{version}; cannot compare with {required_version!r}",
        )
    if verdict:
        return CheckResult("tofu", CheckStatus.OK, f"{version} ({binary})")
    return CheckResult(
        "tofu",
        CheckStatus.FAIL,
        f"{version} does not satisfy {required_version}",
        fix=f"install an OpenTofu matching {required_version}",
    )


def _provider_roots() -> tuple[tuple[str, Path], ...]:
    roots: list[tuple[str, Path]] = []
    for variable in ("NIX_TERRAFORM_PLUGIN_DIR", "TF_PLUGIN_CACHE_DIR"):
        value = os.environ.get(variable)
        if value:
            roots.append((variable, Path(value).expanduser()))
    return tuple(roots)


def _versions_in(base: Path) -> set[str]:
    if not base.is_dir():
        return set()
    return {child.name for child in base.iterdir() if child.is_dir() and parse_version(child.name)}


def _newest(versions: set[str]) -> str:
    return max(versions, key=lambda version: parse_version(version) or ())


def check_providers(required: Mapping[str, Mapping[str, str]]) -> CheckResult:
    """Check that required providers are present in the mirror/cache."""

    if not required:
        return CheckResult("providers", CheckStatus.SKIP, "the stack requires no providers")

    roots = _provider_roots()
    if not roots:
        return CheckResult(
            "providers",
            CheckStatus.SKIP,
            "no mirror or cache set; tofu downloads providers during init",
        )

    for variable, root in roots:
        if not root.exists():
            return CheckResult(
                "providers",
                CheckStatus.FAIL,
                f"{variable}={root} does not exist",
                fix="unset it, or point it at a readable directory",
            )

    problems: list[str] = []
    found: list[str] = []
    for name, spec in sorted(required.items()):
        source = spec.get("source") or name
        constraint_text = spec.get("version") or ""
        available: set[str] = set()
        for _variable, root in roots:
            available |= _versions_in(root / _REGISTRY / source)
        if not available:
            problems.append(f"{name}: not in the mirror")
            continue
        constraints = parse_constraints(constraint_text) if constraint_text else None
        if constraints is None:
            found.append(f"{name} {_newest(available)}")
            continue
        matching = {version for version in available if satisfies(version, constraints)}
        if matching:
            found.append(f"{name} {_newest(matching)}")
        else:
            problems.append(
                f"{name}: none of {', '.join(sorted(available))} satisfies {constraint_text}"
            )

    if problems:
        return CheckResult(
            "providers",
            CheckStatus.FAIL,
            "; ".join(problems),
            fix="use packages.<system>.with-tofu, or run tofu init once",
        )
    return CheckResult("providers", CheckStatus.OK, ", ".join(found))


def check_workdir(workdir: Path) -> CheckResult:
    """Check that the working directory is writable or can be created."""

    target = Path(workdir).expanduser()
    if target.exists():
        if not target.is_dir():
            return CheckResult("workdir", CheckStatus.FAIL, f"{target} is not a directory")
        if not os.access(target, os.W_OK):
            return CheckResult(
                "workdir", CheckStatus.FAIL, f"{target} is not writable", fix=f"chmod u+w {target}"
            )
        return CheckResult("workdir", CheckStatus.OK, str(target))

    ancestor = target
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if ancestor.exists() and os.access(ancestor, os.W_OK):
        return CheckResult("workdir", CheckStatus.OK, f"{target} (creatable)")
    return CheckResult(
        "workdir",
        CheckStatus.FAIL,
        f"{target} cannot be created",
        fix=f"mkdir -p {target}",
    )


def run_checks(
    binary: str,
    required_version: str,
    required_providers: Mapping[str, Mapping[str, str]],
    workdir: Path,
) -> tuple[CheckResult, ...]:
    """Run every local-toolchain check in display order."""

    return (
        check_binary(binary, required_version),
        check_providers(required_providers),
        check_workdir(workdir),
    )


__all__ = [
    "Constraint",
    "check_binary",
    "check_providers",
    "check_workdir",
    "parse_constraints",
    "parse_version",
    "run_checks",
    "satisfies",
    "tofu_version",
]
