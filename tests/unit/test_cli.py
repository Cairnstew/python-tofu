from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = ROOT / "examples" / "gcp_bootstrap" / "infra.py"


def _combined(result) -> str:
    return result.output + getattr(result, "stderr", "")


def test_help(runner: CliRunner, cli) -> None:
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    for command in ("render", "init", "plan", "apply", "destroy", "output"):
        assert command in result.output


def test_render_writes_hcl(runner: CliRunner, cli, config_file: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "tofu"
    result = runner.invoke(
        cli,
        ["render", "--config", str(config_file), "--workdir", str(workdir)],
    )
    assert result.exit_code == 0, _combined(result)
    assert "Rendered" in result.output
    assert (workdir / "main.tf").is_file()
    assert "google_storage_bucket" in (workdir / "main.tf").read_text()


def test_render_missing_config_fails(runner: CliRunner, cli, tmp_path: Path) -> None:
    result = runner.invoke(
        cli,
        ["render", "--config", str(tmp_path / "nope.py"), "--workdir", str(tmp_path / "w")],
    )
    assert result.exit_code == 1
    assert "not found" in _combined(result)


def test_plan_uses_fake_tofu(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path, fake_tofu: Path
) -> None:
    workdir = tmp_path / "tofu"
    result = runner.invoke(
        cli,
        [
            "plan",
            "--config",
            str(config_file),
            "--workdir",
            str(workdir),
            "--binary",
            str(fake_tofu),
            "--no-init",
        ],
    )
    assert result.exit_code == 0, _combined(result)
    assert "Plan: 1 to create" in result.output
    assert "1 to update" in result.output


def test_plan_json_summary(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path, fake_tofu: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "plan",
            "--config",
            str(config_file),
            "--workdir",
            str(tmp_path / "tofu"),
            "--binary",
            str(fake_tofu),
            "--no-init",
            "--json",
        ],
    )
    assert result.exit_code == 0, _combined(result)
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["create"] == 1
    assert payload["update"] == 1
    assert payload["has_changes"] is True


def test_init_and_validate_use_fake_tofu(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path, fake_tofu: Path
) -> None:
    for command in ("init", "validate"):
        result = runner.invoke(
            cli,
            [
                command,
                "--config",
                str(config_file),
                "--workdir",
                str(tmp_path / command),
                "--binary",
                str(fake_tofu),
            ],
        )
        assert result.exit_code == 0, _combined(result)
        assert "fake-tofu" in result.output


def test_output_reads_json(runner: CliRunner, cli, tmp_path: Path, fake_tofu: Path) -> None:
    workdir = tmp_path / "tofu"
    workdir.mkdir()
    result = runner.invoke(
        cli,
        ["output", "--workdir", str(workdir), "--binary", str(fake_tofu)],
    )
    assert result.exit_code == 0, _combined(result)
    assert "demo-project-artifacts" in result.output


def test_output_missing_workdir_fails(runner: CliRunner, cli, tmp_path: Path) -> None:
    result = runner.invoke(cli, ["output", "--workdir", str(tmp_path / "missing")])
    assert result.exit_code == 1
    assert "working directory does not exist" in _combined(result)


def test_verbose_prints_command(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path, fake_tofu: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "init",
            "--config",
            str(config_file),
            "--workdir",
            str(tmp_path / "tofu"),
            "--binary",
            str(fake_tofu),
            "--verbose",
        ],
    )
    assert result.exit_code == 0, _combined(result)
    assert "$ " + str(fake_tofu) in result.output


def test_example_config_renders(runner: CliRunner, cli, tmp_path: Path) -> None:
    result = runner.invoke(
        cli,
        ["render", "--config", str(EXAMPLE_CONFIG), "--workdir", str(tmp_path / "example")],
    )
    assert result.exit_code == 0, _combined(result)
    assert "example-bootstrap" in (tmp_path / "example" / "main.tf").read_text()


def test_failing_tofu_exits_with_its_code(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path
) -> None:
    binary = tmp_path / "bad-tofu"
    binary.write_text("#!/bin/sh\necho 'provider error' >&2\nexit 3\n")
    binary.chmod(0o755)

    result = runner.invoke(
        cli,
        [
            "init",
            "--config",
            str(config_file),
            "--workdir",
            str(tmp_path / "tofu"),
            "--binary",
            str(binary),
        ],
    )
    assert result.exit_code == 3
    assert "provider error" in _combined(result)
