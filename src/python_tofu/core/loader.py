"""Load a Python infrastructure module into a validated provider stack."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, TypeVar

from python_tofu.core.exceptions import ConfigError
from python_tofu.core.models import BaseStack
from python_tofu.core.nix import eval_nix_json

StackT = TypeVar("StackT", bound=BaseStack)

#: Extensions the loader understands, in error text order.
SUPPORTED_SUFFIXES = (".py", ".json", ".nix")


def _load_module(path: Path) -> ModuleType:
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    module_name = f"_python_tofu_config_{digest}"
    # ``submodule_search_locations`` makes relative imports (``from .parts ...``)
    # resolve inside the config's own directory instead of failing because the
    # synthetic module is not part of a package.
    spec = importlib.util.spec_from_file_location(
        module_name, path, submodule_search_locations=[str(path.parent)]
    )
    if spec is None or spec.loader is None:
        raise ConfigError(f"cannot import {path}: not a Python source file")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    # A console-script entry point puts its own ``bin`` directory first on
    # ``sys.path``, so sibling modules next to the config are otherwise
    # unimportable. Add the config directory for the duration of the import.
    search_path = str(path.parent)
    inserted = search_path not in sys.path
    if inserted:
        sys.path.insert(0, search_path)
    try:
        spec.loader.exec_module(module)
    except ConfigError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface the original traceback text
        raise ConfigError(f"error while importing {path}: {exc}") from exc
    finally:
        sys.modules.pop(module_name, None)
        if inserted and search_path in sys.path:
            sys.path.remove(search_path)
    return module


def _coerce(candidate: Any, path: Path, stack_type: type[StackT]) -> StackT:
    if isinstance(candidate, stack_type):
        return candidate
    if isinstance(candidate, dict):
        # ``{ stack = ...; }`` is the convention every authoring front-end
        # shares, so a Nix/JSON wrapper is unwrapped before validation. A bare
        # mapping is accepted too.
        if "stack" in candidate and isinstance(candidate["stack"], dict):
            candidate = candidate["stack"]
        try:
            return stack_type.model_validate(candidate)
        except Exception as exc:  # noqa: BLE001 - re-raise as a config error
            raise ConfigError(f"invalid stack in {path}: {exc}") from exc
    raise ConfigError(
        f"{path} must expose a `stack` that is a {stack_type.__name__} or a mapping, "
        f"got {type(candidate).__name__}"
    )


def _load_data(path: Path) -> Any:
    """Load a non-Python config file into the provider's JSON schema."""

    if path.suffix == ".json":
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"cannot read JSON config {path}: {exc}") from exc
    return eval_nix_json(path)


def load_stack(path: str | Path, stack_type: type[StackT]) -> StackT:
    """Load ``path`` and return its ``stack`` as ``stack_type``.

    ``.py`` configs expose a module-level ``stack``. ``.json`` and ``.nix``
    configs evaluate to either the stack mapping or ``{ "stack": ... }``; both
    are validated by the same provider models, so the guardrails are identical
    regardless of the authoring language.
    """

    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ConfigError(f"config file not found: {resolved}")
    if resolved.suffix not in SUPPORTED_SUFFIXES:
        raise ConfigError(f"config file must be a .py, .json or .nix file: {resolved}")

    if resolved.suffix != ".py":
        return _coerce(_load_data(resolved), resolved, stack_type)

    module = _load_module(resolved)
    if not hasattr(module, "stack"):
        raise ConfigError(f"{resolved} must define a module-level `stack`")
    return _coerce(module.stack, resolved, stack_type)
