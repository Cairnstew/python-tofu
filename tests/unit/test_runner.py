from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from python_tofu.exceptions import TofuCommandError, TofuNotInstalledError
from python_tofu.models.results import PlanSummary
from python_tofu.services.runner import TofuRunner


def _completed(command: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


def test_init_builds_expected_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return _completed(command, stdout="initialised")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = TofuRunner(tmp_path, binary="/usr/bin/tofu").init(upgrade=True)

    assert result.ok
    assert result.command == ["/usr/bin/tofu", "init", "-input=false", "-upgrade"]
    command, kwargs = calls[0]
    assert command == result.command
    assert kwargs["cwd"] == tmp_path
    assert kwargs["check"] is False


def test_plan_arguments(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        return _completed(command)

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = TofuRunner(tmp_path)
    runner.plan(plan_file="plan.tfplan", destroy=True, var_file="prod.tfvars")

    assert seen[0][1:] == [
        "plan",
        "-input=false",
        "-no-color",
        "-destroy",
        "-var-file",
        "prod.tfvars",
        "-out",
        "plan.tfplan",
    ]


def test_repeated_var_files_and_vars(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        return _completed(command)

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = TofuRunner(tmp_path)
    runner.plan(var_file=["a.tfvars", "b.tfvars"], vars=["region=eu", "zone=us"])
    runner.destroy(var_file="prod.tfvars", vars=["project=demo"])

    assert seen[0][1:] == [
        "plan",
        "-input=false",
        "-no-color",
        "-var-file",
        "a.tfvars",
        "-var-file",
        "b.tfvars",
        "-var",
        "region=eu",
        "-var",
        "zone=us",
    ]
    assert seen[1][1:] == [
        "destroy",
        "-no-color",
        "-var-file",
        "prod.tfvars",
        "-var",
        "project=demo",
    ]


def test_apply_and_destroy_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        return _completed(command)

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = TofuRunner(tmp_path)
    runner.apply(auto_approve=True, plan_file="plan.tfplan")
    runner.destroy(auto_approve=True)

    assert seen[0][1:] == ["apply", "-no-color", "-auto-approve", "plan.tfplan"]
    assert seen[1][1:] == ["destroy", "-no-color", "-auto-approve"]


def test_output_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        return _completed(command, stdout='{"x": {"value": 1}}')

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = TofuRunner(tmp_path).output()
    assert seen[0][-1] == "-json"
    assert result.stdout == '{"x": {"value": 1}}'


def test_missing_binary_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(TofuNotInstalledError):
        TofuRunner(tmp_path, binary="missing-tofu").init()


def test_show_json_parses_and_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = {"resource_changes": [{"change": {"actions": ["create"]}}]}

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **_: _completed(command, stdout=json.dumps(payload)),
    )
    assert TofuRunner(tmp_path).show_json("plan.tfplan") == payload

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **_: _completed(command, returncode=1, stderr="bad plan"),
    )
    with pytest.raises(TofuCommandError):
        TofuRunner(tmp_path).show_json("missing.tfplan")


def test_plan_summary_counts_actions() -> None:
    payload = {
        "resource_changes": [
            {"change": {"actions": ["create"]}},
            {"change": {"actions": ["create"]}},
            {"change": {"actions": ["update"]}},
            {"change": {"actions": ["delete"]}},
            {"change": {"actions": ["create", "delete"]}},
            {"change": {"actions": ["no-op"]}},
            {"change": {"actions": []}},
        ]
    }
    summary = PlanSummary.from_show_json(payload)
    assert (summary.create, summary.update, summary.delete) == (2, 1, 1)
    assert (summary.replace, summary.no_op, summary.other) == (1, 1, 1)
    assert summary.total == 7
    assert summary.has_changes

    empty = PlanSummary.from_show_json({})
    assert not empty.has_changes
    assert empty.total == 0


def test_environment_is_merged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs["env"])  # type: ignore[arg-type]
        return _completed(command)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("EXISTING", "1")
    TofuRunner(tmp_path, env={"EXTRA": "2"}).init()
    assert captured["EXISTING"] == "1"
    assert captured["EXTRA"] == "2"
