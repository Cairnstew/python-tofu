from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from python_tofu.core.cli.base import format_limit
from python_tofu.core.limits import LimitCheck, LimitPeriod

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = ROOT / "examples" / "gcp_bootstrap" / "infra.py"


def _combined(result) -> str:
    return result.output + getattr(result, "stderr", "")


def test_format_limit_keeps_small_nonzero_usage() -> None:
    check = LimitCheck(
        key="gcp.storage.standard_gb",
        area="storage",
        unit="GB",
        used=0.001,
        amount=5,
        period=LimitPeriod.MONTH,
    )
    assert "0.001/5 GB" in format_limit(check)


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


def test_binary_comes_from_the_environment(
    runner: CliRunner,
    cli,
    config_file: Path,
    tmp_path: Path,
    fake_tofu: Path,
    monkeypatch,
) -> None:
    """The Nix wrapper selects `tofu` without changing every call site."""

    monkeypatch.setenv("PYTHON_TOFU_BINARY", str(fake_tofu))
    result = runner.invoke(
        cli,
        [
            "plan",
            "--config",
            str(config_file),
            "--workdir",
            str(tmp_path / "tofu"),
            "--no-init",
            "--verbose",
        ],
    )
    assert result.exit_code == 0, _combined(result)
    assert str(fake_tofu) in _combined(result)


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


def test_plan_exit_code_exits_2_with_changes(
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
            "--exit-code",
        ],
    )

    assert result.exit_code == 2, _combined(result)
    assert "Plan: 1 to create" in result.output


def _quiet_tofu(tmp_path: Path) -> Path:
    """A fake ``tofu`` whose plan is empty and whose summary has no changes."""

    binary = tmp_path / "quiet-tofu"
    binary.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        '  show) echo \'{"resource_changes":[{"change":{"actions":["no-op"]}}]}\' ;;\n'
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary


def test_plan_exit_code_exits_0_without_changes(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path
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
            str(_quiet_tofu(tmp_path)),
            "--no-init",
            "--exit-code",
        ],
    )

    assert result.exit_code == 0, _combined(result)
    assert "Plan: no changes" in result.output


def test_plan_exit_code_exits_1_when_summary_is_unavailable(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path
) -> None:
    binary = tmp_path / "broken-show"
    binary.write_text(
        '#!/bin/sh\ncase "$1" in\n  show) echo "boom" >&2; exit 1 ;;\nesac\nexit 0\n',
        encoding="utf-8",
    )
    binary.chmod(0o755)

    result = runner.invoke(
        cli,
        [
            "plan",
            "--config",
            str(config_file),
            "--workdir",
            str(tmp_path / "tofu"),
            "--binary",
            str(binary),
            "--no-init",
            "--exit-code",
        ],
    )

    assert result.exit_code == 1, _combined(result)
    assert "Could not parse plan summary" in _combined(result)


def test_plan_without_exit_code_stays_0_with_changes(
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
        ],
    )

    assert result.exit_code == 0, _combined(result)


def _recording_tofu(tmp_path: Path, record: Path) -> Path:
    """A fake ``tofu`` that records the arguments of plan/apply invocations."""

    binary = tmp_path / "recording-tofu"
    binary.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f'  plan|apply|destroy) printf "%s\\n" "$@" > "{record}" ;;\n'
        '  show) echo "{}" ;;\n'
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary


def test_version(runner: CliRunner, cli) -> None:
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0, _combined(result)
    assert result.output.startswith("python-tofu ")


def test_plan_relative_workdir_uses_absolute_plan_and_var_paths(
    runner: CliRunner,
    cli,
    config_file: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    record = tmp_path / "args.txt"
    binary = _recording_tofu(tmp_path, record)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        [
            "plan",
            "--config",
            "infra.py",
            "--workdir",
            "out",
            "--binary",
            str(binary),
            "--no-init",
            "--var-file",
            "extra.tfvars",
        ],
    )
    assert result.exit_code == 0, _combined(result)

    args = record.read_text().splitlines()
    assert Path(args[args.index("-out") + 1]).is_absolute()
    assert Path(args[args.index("-var-file") + 1]).is_absolute()


def test_apply_plan_file_resolves_against_cwd(
    runner: CliRunner,
    cli,
    tmp_path: Path,
    monkeypatch,
) -> None:
    record = tmp_path / "args.txt"
    binary = _recording_tofu(tmp_path, record)
    (tmp_path / "out").mkdir()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        [
            "apply",
            "--plan-file",
            "plan.tfplan",
            "--workdir",
            "out",
            "--binary",
            str(binary),
            "--auto-approve",
        ],
    )
    assert result.exit_code == 0, _combined(result)

    args = record.read_text().splitlines()
    assert args[-1] == str(tmp_path / "plan.tfplan")


def test_workdir_expands_tilde(
    runner: CliRunner,
    cli,
    config_file: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(
        cli,
        ["render", "--config", str(config_file), "--workdir", "~/tofu"],
    )
    assert result.exit_code == 0, _combined(result)
    assert (tmp_path / "tofu" / "main.tf").is_file()


def _config_exceeding_free_tier(tmp_path: Path) -> Path:
    path = tmp_path / "over.py"
    path.write_text(
        """\
from python_tofu import GcpProvider, GcpStack, StorageBucket

stack = GcpStack(
    provider=GcpProvider(project="demo-project"),
    buckets=[
        StorageBucket(
            project="demo-project",
            name="demo-artifacts",
            location="us-central1",
            estimated_size_gb=9,
        )
    ],
)
""",
        encoding="utf-8",
    )
    return path


def test_render_blocks_on_limit_violation(runner: CliRunner, cli, tmp_path: Path) -> None:
    config = _config_exceeding_free_tier(tmp_path)
    result = runner.invoke(
        cli,
        ["render", "--config", str(config), "--workdir", str(tmp_path / "w")],
    )
    assert result.exit_code == 1
    output = _combined(result)
    assert "always-free tier exceeded" in output
    assert "gcp.storage.standard_gb" in output


def test_limits_warn_mode_continues(runner: CliRunner, cli, tmp_path: Path) -> None:
    config = _config_exceeding_free_tier(tmp_path)
    result = runner.invoke(
        cli,
        [
            "render",
            "--config",
            str(config),
            "--workdir",
            str(tmp_path / "w"),
            "--limits",
            "warn",
        ],
    )
    assert result.exit_code == 0, _combined(result)
    assert "Warning: gcp.storage.standard_gb" in _combined(result)
    assert (tmp_path / "w" / "main.tf").is_file()


def test_limits_off_mode_is_silent(runner: CliRunner, cli, tmp_path: Path) -> None:
    config = _config_exceeding_free_tier(tmp_path)
    result = runner.invoke(
        cli,
        [
            "render",
            "--config",
            str(config),
            "--workdir",
            str(tmp_path / "w"),
            "--limits",
            "off",
        ],
    )
    assert result.exit_code == 0, _combined(result)
    assert "Warning" not in _combined(result)


def test_limits_command_reports_usage(runner: CliRunner, cli, tmp_path: Path) -> None:
    config = _config_exceeding_free_tier(tmp_path)
    result = runner.invoke(cli, ["limits", "--config", str(config)])
    assert result.exit_code == 0, _combined(result)
    output = _combined(result)
    assert "gcp.storage.standard_gb" in output
    assert "gcp.free_tier.total" in output
    assert "!" in output


def test_limits_command_json(runner: CliRunner, cli, tmp_path: Path) -> None:
    config = _config_exceeding_free_tier(tmp_path)
    result = runner.invoke(cli, ["limits", "--config", str(config), "--json"])
    assert result.exit_code == 0, _combined(result)
    payload = json.loads(result.output.strip().splitlines()[-1])
    checks = {check["key"]: check for check in payload["checks"]}
    assert checks["gcp.storage.standard_gb"]["used"] == 9
    assert checks["gcp.storage.standard_gb"]["exceeded"] is True
    assert payload["errors"] >= 1


def test_limits_command_all_includes_unused(runner: CliRunner, cli, tmp_path: Path) -> None:
    config = _config_exceeding_free_tier(tmp_path)
    result = runner.invoke(cli, ["limits", "--config", str(config), "--all"])
    assert result.exit_code == 0, _combined(result)
    assert "gcp.bigquery.query_tib" in _combined(result)


def _config_within_free_tier(tmp_path: Path) -> Path:
    path = tmp_path / "small.py"
    path.write_text(
        """\
from python_tofu import GcpProvider, GcpStack, StorageBucket

stack = GcpStack(
    provider=GcpProvider(project="demo-project"),
    buckets=[
        StorageBucket(
            project="demo-project",
            name="demo-artifacts",
            location="us-central1",
            estimated_size_gb=1,
        )
    ],
)
""",
        encoding="utf-8",
    )
    return path


def test_limits_command_summarises_unknowns(runner: CliRunner, cli, tmp_path: Path) -> None:
    config = _config_within_free_tier(tmp_path)
    result = runner.invoke(cli, ["limits", "--config", str(config)])
    assert result.exit_code == 0, _combined(result)
    output = _combined(result)
    assert "unknown" in output
    assert "use --all to list them" in output


def test_limits_all_marks_unknown_limits(runner: CliRunner, cli, tmp_path: Path) -> None:
    config = _config_within_free_tier(tmp_path)
    result = runner.invoke(cli, ["limits", "--config", str(config), "--all"])
    assert result.exit_code == 0, _combined(result)
    assert "? gcp.bigquery.query_tib: unknown/1 TiB" in _combined(result)


def test_fail_on_unknown_blocks_render(runner: CliRunner, cli, tmp_path: Path) -> None:
    config = _config_within_free_tier(tmp_path)
    result = runner.invoke(
        cli,
        [
            "render",
            "--config",
            str(config),
            "--workdir",
            str(tmp_path / "w"),
            "--fail-on-unknown",
        ],
    )
    assert result.exit_code == 1, _combined(result)
    assert "could not be measured" in _combined(result)


def test_limits_usage_live_measures_inventory(
    monkeypatch, runner: CliRunner, cli, tmp_path: Path
) -> None:
    from python_tofu.providers.gcp import live

    monkeypatch.setattr(live, "access_token", lambda stack: "token")

    def fake_list(project: str, token: str, asset_type: str) -> list[dict]:
        if asset_type == live.INSTANCE_TYPE:
            return [
                {
                    "machineType": "https://www.googleapis.com/compute/v1/projects/demo-project/"
                    "zones/us-central1-a/machineTypes/e2-micro",
                    "zone": "https://www.googleapis.com/compute/v1/projects/demo-project/"
                    "zones/us-central1-a",
                    "scheduling": {"preemptible": False, "provisioningModel": "STANDARD"},
                }
            ]
        return []

    monkeypatch.setattr(live, "list_assets", fake_list)
    config = _config_within_free_tier(tmp_path)
    result = runner.invoke(cli, ["limits", "--config", str(config), "--usage", "live", "--all"])
    assert result.exit_code == 0, _combined(result)
    output = _combined(result)
    assert "gcp.compute.e2_micro_hours: 720/720 hours (100.0%)" in output
    # Stack-declared bucket size still counts when inventory cannot measure it.
    assert "gcp.storage.standard_gb: 1/5 GB" in output
    # Byte-based limits inventory cannot see stay unknown rather than 0.
    assert "? gcp.bigquery.query_tib: unknown/1 TiB" in output


def test_usage_live_failure_is_a_clean_error(
    monkeypatch, runner: CliRunner, cli, tmp_path: Path
) -> None:
    from python_tofu.providers.gcp import live

    def boom(stack):
        raise live.LiveUsageError("could not obtain Google credentials: missing key")

    monkeypatch.setattr(live, "access_token", boom)
    config = _config_within_free_tier(tmp_path)
    result = runner.invoke(
        cli,
        ["render", "--config", str(config), "--workdir", str(tmp_path / "w"), "--usage", "live"],
    )
    assert result.exit_code == 1
    assert "Error: could not obtain Google credentials" in _combined(result)
    assert "Traceback" not in _combined(result)


def test_limits_off_skips_live_measurement(
    monkeypatch, runner: CliRunner, cli, tmp_path: Path
) -> None:
    from python_tofu.providers.gcp import live

    def boom(stack):
        raise AssertionError("live measurement must not run with --limits off")

    monkeypatch.setattr(live, "access_token", boom)
    config = _config_within_free_tier(tmp_path)
    result = runner.invoke(
        cli,
        [
            "render",
            "--config",
            str(config),
            "--workdir",
            str(tmp_path / "w"),
            "--usage",
            "live",
            "--limits",
            "off",
        ],
    )
    assert result.exit_code == 0, _combined(result)


def test_missing_binary_reports_clean_error(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path
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
            str(tmp_path / "nope"),
        ],
    )
    assert result.exit_code == 1
    output = _combined(result)
    assert "was not found" in output
    assert "Traceback" not in output


def test_apply_plan_file_missing_workdir_fails(runner: CliRunner, cli, tmp_path: Path) -> None:
    result = runner.invoke(
        cli,
        [
            "apply",
            "--plan-file",
            "plan.tfplan",
            "--workdir",
            str(tmp_path / "missing"),
        ],
    )
    assert result.exit_code == 1
    assert "working directory does not exist" in _combined(result)


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


def test_plan_passes_repeated_variables(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path, monkeypatch
) -> None:
    record = tmp_path / "args.txt"
    binary = _recording_tofu(tmp_path, record)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        [
            "plan",
            "--config",
            str(config_file),
            "--workdir",
            "out",
            "--binary",
            str(binary),
            "--no-init",
            "--var-file",
            "a.tfvars",
            "--var-file",
            "b.tfvars",
            "--var",
            "region=europe-west1",
        ],
    )
    assert result.exit_code == 0, _combined(result)

    args = record.read_text().splitlines()
    assert args.count("-var-file") == 2
    assert Path(args[args.index("-var-file") + 1]).is_absolute()
    assert args.count("-var") == 1
    assert args[args.index("-var") + 1] == "region=europe-west1"


def test_destroy_passes_variables(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path, monkeypatch
) -> None:
    record = tmp_path / "args.txt"
    binary = _recording_tofu(tmp_path, record)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        [
            "destroy",
            "--config",
            str(config_file),
            "--workdir",
            "out",
            "--binary",
            str(binary),
            "--auto-approve",
            "--var-file",
            "prod.tfvars",
            "--var",
            "project=demo",
        ],
    )
    assert result.exit_code == 0, _combined(result)

    args = record.read_text().splitlines()
    assert args.count("-var-file") == 1
    assert args[args.index("-var") + 1] == "project=demo"


def test_apply_rejects_variables_with_saved_plan(runner: CliRunner, cli, tmp_path: Path) -> None:
    workdir = tmp_path / "out"
    workdir.mkdir()
    plan = tmp_path / "plan.tfplan"
    plan.write_text("")

    result = runner.invoke(
        cli,
        [
            "apply",
            "--plan-file",
            str(plan),
            "--workdir",
            str(workdir),
            "--var",
            "project=demo",
        ],
    )
    assert result.exit_code == 1
    assert "variables cannot be set" in _combined(result)


def test_render_check_reports_up_to_date(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "tofu"
    first = runner.invoke(cli, ["render", "--config", str(config_file), "--workdir", str(workdir)])
    assert first.exit_code == 0, _combined(first)

    result = runner.invoke(
        cli,
        ["render", "--config", str(config_file), "--workdir", str(workdir), "--check"],
    )
    assert result.exit_code == 0, _combined(result)
    assert "HCL is up to date" in result.output


def test_render_check_detects_drift_without_writing(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "tofu"
    first = runner.invoke(cli, ["render", "--config", str(config_file), "--workdir", str(workdir)])
    assert first.exit_code == 0, _combined(first)
    (workdir / "main.tf").write_text("# edited by hand\n")
    (workdir / "versions.tf").unlink()

    result = runner.invoke(
        cli,
        ["render", "--config", str(config_file), "--workdir", str(workdir), "--check"],
    )
    assert result.exit_code == 1
    output = _combined(result)
    assert "HCL is out of date (2 of 4 files)" in output
    assert "main.tf" in output
    assert "versions.tf" in output
    # --check never repairs the workdir.
    assert (workdir / "main.tf").read_text() == "# edited by hand\n"
    assert not (workdir / "versions.tf").exists()


def test_render_check_missing_workdir_is_out_of_date(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "render",
            "--config",
            str(config_file),
            "--workdir",
            str(tmp_path / "missing"),
            "--check",
        ],
    )
    assert result.exit_code == 1
    assert "HCL is out of date" in _combined(result)


def test_render_diff_shows_the_change(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "tofu"
    first = runner.invoke(cli, ["render", "--config", str(config_file), "--workdir", str(workdir)])
    assert first.exit_code == 0, _combined(first)
    (workdir / "main.tf").write_text("# edited by hand\n")

    result = runner.invoke(
        cli,
        ["render", "--config", str(config_file), "--workdir", str(workdir), "--diff"],
    )
    assert result.exit_code == 1
    output = _combined(result)
    assert "--- a/main.tf" in output
    assert "+++ b/main.tf" in output
    assert "-resource" in output or "+resource" in output


def test_render_stdout_prints_without_writing(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "tofu"
    result = runner.invoke(
        cli,
        [
            "render",
            "--config",
            str(config_file),
            "--workdir",
            str(workdir),
            "--stdout",
            "main.tf",
        ],
    )
    assert result.exit_code == 0, _combined(result)
    assert "google_storage_bucket" in result.output
    assert not workdir.exists()


def test_render_stdout_rejects_unknown_file(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path
) -> None:
    result = runner.invoke(
        cli,
        ["render", "--config", str(config_file), "--stdout", "nope.tf"],
    )
    assert result.exit_code == 1
    assert "no rendered file named 'nope.tf'" in _combined(result)


def test_render_check_and_stdout_conflict(
    runner: CliRunner, cli, config_file: Path, tmp_path: Path
) -> None:
    result = runner.invoke(
        cli,
        ["render", "--config", str(config_file), "--check", "--stdout", "main.tf"],
    )
    assert result.exit_code == 1
    assert "cannot be combined" in _combined(result)
