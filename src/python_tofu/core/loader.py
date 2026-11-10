"""Load a Python infrastructure module into a validated provider stack."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, TypeVar

from python_tofu.core.exceptions import ConfigError
from python_tofu.core.models import BaseStack

StackT = TypeVar("StackT", bound=BaseStack)


def _load_module(path: Path) -> ModuleType:
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    module_name = f"_python_tofu_config_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ConfigError(f"cannot import {path}: not a Python source file")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except ConfigError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface the original traceback text
        raise ConfigError(f"error while importing {path}: {exc}") from exc
    finally:
        sys.modules.pop(module_name, None)
    return module


def _coerce(candidate: Any, path: Path, stack_type: type[StackT]) -> StackT:
    if isinstance(candidate, stack_type):
        return candidate
    if isinstance(candidate, dict):
        try:
            return stack_type.model_validate(candidate)
        except Exception as exc:  # noqa: BLE001 - re-raise as a config error
            raise ConfigError(f"invalid stack in {path}: {exc}") from exc
    raise ConfigError(
        f"{path} must expose a `stack` that is a {stack_type.__name__} or a mapping, "
        f"got {type(candidate).__name__}"
    )


def load_stack(path: str | Path, stack_type: type[StackT]) -> StackT:
    """Import ``path`` and return its module-level ``stack`` as ``stack_type``.

    The config module may either construct the provider stack directly or
    expose a plain mapping, which is validated on load.
    """

    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ConfigError(f"config file not found: {resolved}")
    if resolved.suffix != ".py":
        raise ConfigError(f"config file must be a .py module: {resolved}")

    module = _load_module(resolved)
    if not hasattr(module, "stack"):
        raise ConfigError(f"{resolved} must define a module-level `stack`")
    return _coerce(module.stack, resolved, stack_type)
