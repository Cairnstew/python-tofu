from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from python_tofu.core.exceptions import ConfigError
from python_tofu.core.nix import (
    NIX_ENV,
    NIX_IMPURE_ENV,
    eval_nix_json,
    nix_eval_command,
)


def test_missing_nix_binary_is_actionable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(NIX_ENV, raising=False)
    monkeypatch.setattr("python_tofu.core.nix.shutil.which", lambda _name: None)

    with pytest.raises(ConfigError, match="`nix` binary was not found"):
        eval_nix_json(tmp_path / "stack.nix")


def test_command_is_pure_for_a_plain_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "stack.nix"
    path.write_text('{ provider.project = "demo"; }\n', encoding="utf-8")
    monkeypatch.delenv(NIX_ENV, raising=False)
    monkeypatch.delenv(NIX_IMPURE_ENV, raising=False)
    monkeypatch.setattr("python_tofu.core.nix.shutil.which", lambda _name: "/usr/bin/nix")

    command = nix_eval_command(path)

    assert command[:3] == ["/usr/bin/nix", "eval", "--json"]
    assert "--impure" not in command
    assert command[-2:] == ["--apply", "x: if builtins.isFunction x then x { } else x"]


def test_command_opts_into_impure_for_nixpkgs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "stack.nix"
    path.write_text("import <nixpkgs> { }\n", encoding="utf-8")
    monkeypatch.delenv(NIX_ENV, raising=False)
    monkeypatch.delenv(NIX_IMPURE_ENV, raising=False)
    monkeypatch.setattr("python_tofu.core.nix.shutil.which", lambda _name: "/usr/bin/nix")

    assert "--impure" in nix_eval_command(path)


def test_impure_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "stack.nix"
    path.write_text("{ }\n", encoding="utf-8")
    monkeypatch.delenv(NIX_ENV, raising=False)
    monkeypatch.setenv(NIX_IMPURE_ENV, "1")
    monkeypatch.setattr("python_tofu.core.nix.shutil.which", lambda _name: "/usr/bin/nix")

    assert "--impure" in nix_eval_command(path)


def test_binary_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "stack.nix"
    path.write_text("{ }\n", encoding="utf-8")
    monkeypatch.setenv(NIX_ENV, "/opt/nix/bin/nix")
    monkeypatch.delenv(NIX_IMPURE_ENV, raising=False)

    assert nix_eval_command(path)[0] == "/opt/nix/bin/nix"


def test_eval_parses_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "stack.nix"
    path.write_text("{ }\n", encoding="utf-8")
    monkeypatch.setattr("python_tofu.core.nix.shutil.which", lambda _name: "/usr/bin/nix")
    monkeypatch.setattr(
        "python_tofu.core.nix.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=json.dumps({"provider": {"project": "demo"}}), stderr=""
        ),
    )

    assert eval_nix_json(path) == {"provider": {"project": "demo"}}


def test_eval_surfaces_nix_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "stack.nix"
    path.write_text("{ }\n", encoding="utf-8")
    monkeypatch.setattr("python_tofu.core.nix.shutil.which", lambda _name: "/usr/bin/nix")
    monkeypatch.setattr(
        "python_tofu.core.nix.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="error: undefined variable 'oops'"
        ),
    )

    with pytest.raises(ConfigError, match="undefined variable 'oops'"):
        eval_nix_json(path)


def test_eval_rejects_non_json_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "stack.nix"
    path.write_text("{ }\n", encoding="utf-8")
    monkeypatch.setattr("python_tofu.core.nix.shutil.which", lambda _name: "/usr/bin/nix")
    monkeypatch.setattr(
        "python_tofu.core.nix.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="not json", stderr=""),
    )

    with pytest.raises(ConfigError, match="did not produce JSON"):
        eval_nix_json(path)


def test_eval_wraps_missing_binary_at_exec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "stack.nix"
    path.write_text("{ }\n", encoding="utf-8")
    monkeypatch.setattr("python_tofu.core.nix.shutil.which", lambda _name: "/usr/bin/nix")

    def _raise(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("python_tofu.core.nix.subprocess.run", _raise)
    with pytest.raises(ConfigError, match="was not found"):
        eval_nix_json(path)
