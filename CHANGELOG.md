# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `python-tofu --version`.
- Provider-agnostic limits/throttler in `python_tofu.core.limits`: per-area
  `Limit`s, normalised `AggregateLimit`s, `Usage`, `LimitReport` and
  `LimitExceeded`.
- GCP always-free-tier policy (`providers/gcp/limits.py`) enforced before
  `render`/`init`/`validate`/`plan`/`apply`/`destroy`, with `--limits
  error|warn|off` and a `python-tofu limits` report command.
- `GcpStack.usage_estimates` and `StorageBucket.estimated_size_gb` for declaring
  usage the stack cannot derive.
- `--usage stack|live` and `--fail-on-unknown`. Live mode reads Cloud Asset
  Inventory (free, read-only) so manually created and pre-existing instances,
  disks and GKE clusters count against the free tier.
- `LimitCheck.status` (`ok`/`exceeded`/`unknown`): unmeasured limits are
  reported as `unknown` instead of silently passing as `0%`.

### Changed

- Split the package into a provider-agnostic `python_tofu.core` and a
  `python_tofu.providers.gcp` branch. GCP models, validation quirks and HCL
  shapes now live under `providers/gcp/`; the core exposes a `Provider` plugin
  contract and `build_app(provider)` CLI factory.
- The historical import paths (`python_tofu.models`, `python_tofu.services`,
  `python_tofu.hcl`, `python_tofu.loader`, `python_tofu.exceptions`) remain as
  backwards-compatible re-exports.

### Fixed

- `plan` with a relative `--workdir` (including the documented `.tofu/example`
  quickstart) no longer writes the plan inside a nested workdir path.
- `--plan-file` and `--var-file` are resolved against the current directory
  instead of inside `--workdir`.
- `apply --plan-file` reports a missing work directory instead of a misleading
  "OpenTofu binary not found" error.

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
