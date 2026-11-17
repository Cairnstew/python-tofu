from __future__ import annotations

import json
import subprocess

import pytest


def _eval(declaration: str) -> dict:
    expr = f"""
      let
        flake = builtins.getFlake (toString ./.);
      in
      flake.lib.evalStack {{
        modules = [
          {declaration}
        ];
      }}
    """
    result = subprocess.run(
        ["nix", "eval", "--impure", "--json", "--expr", expr],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.nix
def test_keyed_sections_fill_identity_fields() -> None:
    stack = _eval("""
      {
        provider.project = "demo-project";
        projects.demo-project.name = "Demo";
        service_accounts.ci-runner.project = "demo-project";
        buckets.artifacts = { project = "demo-project"; location = "EU"; };
        pubsub_topics.events.project = "demo-project";
        outputs.bucket-name.value = "\\${google_storage_bucket.bucket_artifacts.name}";
      }
    """)
    assert stack["projects"][0]["project_id"] == "demo-project"
    assert stack["service_accounts"][0]["account_id"] == "ci-runner"
    assert stack["buckets"][0]["name"] == "artifacts"
    assert stack["pubsub_topics"][0]["name"] == "events"
    assert stack["outputs"][0]["name"] == "bucket-name"


@pytest.mark.nix
def test_explicit_identity_wins_over_the_key() -> None:
    stack = _eval("""
      {
        provider.project = "demo-project";
        buckets.local-name.name = "real-bucket-name";
      }
    """)
    assert stack["buckets"][0]["name"] == "real-bucket-name"


@pytest.mark.nix
def test_bucket_object_accepts_a_path_source() -> None:
    stack = _eval("""
      {
        provider.project = "demo-project";
        buckets.artifacts = { project = "demo-project"; };
        bucket_objects."dist/app.js" = {
          bucket = "artifacts";
          source = flake.outPath + "/README.md";
          content_type = "application/javascript";
        };
      }
    """)
    obj = stack["bucket_objects"][0]
    assert obj["name"] == "dist/app.js"
    assert isinstance(obj["source"], str)
    assert obj["source"].endswith("README.md")


@pytest.mark.nix
def test_bucket_object_accepts_text_content() -> None:
    stack = _eval("""
      {
        provider.project = "demo-project";
        buckets.artifacts = { project = "demo-project"; };
        bucket_objects."config/release.json" = {
          bucket = "artifacts";
          content = builtins.toJSON { release = "v1"; };
          content_type = "application/json";
        };
      }
    """)
    obj = stack["bucket_objects"][0]
    assert obj["name"] == "config/release.json"
    assert json.loads(obj["content"]) == {"release": "v1"}


@pytest.mark.nix
def test_reference_string_survives_as_a_plain_string() -> None:
    stack = _eval("""
      {
        provider.project = "demo-project";
        outputs.bucket.value = "\\${google_storage_bucket.bucket_artifacts.name}";
      }
    """)
    assert stack["outputs"][0]["value"] == "${google_storage_bucket.bucket_artifacts.name}"


@pytest.mark.nix
def test_empty_sections_are_rendered_as_empty_lists() -> None:
    stack = _eval('{ provider.project = "demo-project"; }')
    assert stack["buckets"] == []
    assert stack["prune"] == {}
    assert "name" not in stack
    assert "backend" not in stack
    assert "limits_mode" not in stack


@pytest.mark.nix
def test_modules_compose_with_mkmerge() -> None:
    stack = _eval("""
      {
        imports = [ { provider.project = "demo-project"; } ];
        buckets.one = { project = "demo-project"; };
      }
      {
        buckets.two = { project = "demo-project"; };
      }
    """)
    assert {bucket["name"] for bucket in stack["buckets"]} == {"one", "two"}
