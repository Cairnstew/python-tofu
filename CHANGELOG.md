# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-09

### Added

- Typed Pydantic DSL for GCP projects, APIs, service accounts, IAM bindings and
  GCS buckets (`GcpStack`).
- Deterministic, `tofu fmt`-clean HCL writer with attribute alignment and raw
  expressions.
- Renderer with duplicate-address detection, local resource naming and local/GCS
  backend support.
- `TofuRunner` subprocess wrapper for `init`, `validate`, `plan`, `apply`,
  `destroy` and `output`, plus `tofu show -json` plan summaries.
- Typer CLI: `render`, `init`, `validate`, `plan`, `apply`, `destroy`, `output`.
- Python config loader that imports an `infra.py` and validates its `stack`.
- End-to-end GCP bootstrap example (project, APIs, service account, bucket).
- Nix flake with uv2nix builds, dev shells, overlay, NixOS and Home Manager
  modules.
- Unit, integration and Nix-eval test suites with a fake `tofu` binary.
- CI/CD with path-based change detection and reusable workflows.
