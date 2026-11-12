from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from python_tofu.providers.gcp import (
    GcpBackendConfig,
    GcpProvider,
    GcpStack,
    StorageBucket,
)
from python_tofu.providers.gcp.renderer import GcpRenderer

PROJECT = "demo-project"


def _write_config(path: Path, *, name: str | None = None, backend: bool = False) -> Path:
    name_line = f'    name="{name}",\n' if name else ""
    backend_line = (
        '    backend=BackendConfig(kind="gcs", bucket="demo-state"),\n' if backend else ""
    )
    path.write_text(
        f"""\
from python_tofu import BackendConfig, GcpProvider, GcpStack, StorageBucket

stack = GcpStack(
    provider=GcpProvider(project="{PROJECT}"),
{name_line}{backend_line}    buckets=[StorageBucket(project="{PROJECT}", name="demo-artifacts")],
)
""",
        encoding="utf-8",
    )
    return path


def _render(cli, runner: CliRunner, config: Path, *extra: str):
    return runner.invoke(cli, ["render", "--config", str(config), *extra])


# ── default workdir ───────────────────────────────────────────────────
def test_default_workdir_uses_the_config_stem(
    cli, runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write_config(tmp_path / "infra.py")

    result = _render(cli, runner, config)

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".tofu" / "infra" / "main.tf").is_file()


def test_two_configs_get_separate_workdirs(
    cli, runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    dev = _write_config(tmp_path / "dev.py")
    prod = _write_config(tmp_path / "prod.py")

    assert _render(cli, runner, dev).exit_code == 0
    assert _render(cli, runner, prod).exit_code == 0

    assert (tmp_path / ".tofu" / "dev" / "main.tf").is_file()
    assert (tmp_path / ".tofu" / "prod" / "main.tf").is_file()
    assert not (tmp_path / ".tofu" / "main.tf").exists()


def test_explicit_workdir_wins_and_is_not_nested(
    cli, runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write_config(tmp_path / "infra.py", name="prod")

    result = _render(cli, runner, config, "--workdir", "custom")

    assert result.exit_code == 0, result.output
    assert (tmp_path / "custom" / "main.tf").is_file()
    assert not (tmp_path / ".tofu").exists()


def test_stack_name_field_sets_the_default_workdir(
    cli, runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write_config(tmp_path / "infra.py", name="prod")

    result = _render(cli, runner, config)

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".tofu" / "prod" / "main.tf").is_file()


def test_stack_name_option_sets_the_default_workdir(
    cli, runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write_config(tmp_path / "infra.py")

    result = _render(cli, runner, config, "--stack-name", "staging")

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".tofu" / "staging" / "main.tf").is_file()


def test_stack_name_option_beats_the_stack_field(
    cli, runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write_config(tmp_path / "infra.py", name="prod")

    result = _render(cli, runner, config, "--stack-name", "preview")

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".tofu" / "preview" / "main.tf").is_file()


def test_invalid_stack_name_is_rejected(
    cli, runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write_config(tmp_path / "infra.py")

    result = _render(cli, runner, config, "--stack-name", "../escape")

    assert result.exit_code != 0
    assert "stack name" in result.output


def test_output_reads_the_derived_workdir(
    cli, runner: CliRunner, tmp_path: Path, monkeypatch, fake_tofu: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write_config(tmp_path / "infra.py")
    assert _render(cli, runner, config).exit_code == 0

    result = runner.invoke(
        cli,
        ["output", "--config", str(config), "--binary", str(fake_tofu)],
    )

    assert result.exit_code == 0, result.output
    assert "demo-project-artifacts" in result.output


# ── backend prefix ────────────────────────────────────────────────────
def _versions(stack: GcpStack) -> str:
    return GcpRenderer(".tofu").render_text(stack)["versions.tf"]


def _backend_stack(**overrides: object) -> GcpStack:
    values: dict[str, object] = {
        "provider": GcpProvider(project=PROJECT),
        "buckets": [StorageBucket(project=PROJECT, name="demo-artifacts")],
    }
    values.update(overrides)
    return GcpStack(**values)  # type: ignore[arg-type]


def test_backend_prefix_defaults_to_the_stack_name() -> None:
    text = _versions(
        _backend_stack(
            name="api",
            backend=GcpBackendConfig(kind="gcs", bucket="demo-state"),
        )
    )

    assert 'prefix = "python-tofu/api"' in text


def test_explicit_backend_prefix_is_honoured() -> None:
    text = _versions(
        _backend_stack(
            name="api",
            backend=GcpBackendConfig(kind="gcs", bucket="demo-state", prefix="team/api"),
        )
    )

    assert 'prefix = "team/api"' in text
    assert "python-tofu/api" not in text


def test_backend_prefix_without_a_name_keeps_the_shared_default() -> None:
    text = _versions(_backend_stack(backend=GcpBackendConfig(kind="gcs", bucket="demo-state")))

    assert 'prefix = "python-tofu/state"' in text


def test_cli_sets_the_stack_name_on_the_rendered_prefix(
    cli, runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write_config(tmp_path / "infra.py", backend=True)

    result = _render(cli, runner, config, "--stack-name", "api")

    assert result.exit_code == 0, result.output
    versions = (tmp_path / ".tofu" / "api" / "versions.tf").read_text()
    assert 'prefix = "python-tofu/api"' in versions


# ── model validation ──────────────────────────────────────────────────
@pytest.mark.parametrize("name", ["../escape", "a/b", "with space", "-lead", ""])
def test_stack_name_must_be_path_safe(name: str) -> None:
    with pytest.raises(ValidationError, match="stack name"):
        _backend_stack(name=name)
