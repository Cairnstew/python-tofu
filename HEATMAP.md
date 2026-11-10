# Change Heatmap

## Hot (changes every feature)

| File | Rationale |
|------|-----------|
| `src/python_tofu/providers/gcp/models.py` | New GCP resource types and fields |
| `src/python_tofu/providers/gcp/renderer.py` | New resource → HCL mappings |
| `src/python_tofu/core/cli/commands/` | New commands and options |
| `examples/gcp_bootstrap/infra.py` | Living example / integration surface |
| `.github/workflows/ci.yml` | Path filters |

## Warm (changes per major version / new provider)

| File | Rationale |
|------|-----------|
| `src/python_tofu/core/renderer.py` | Managed-file contract, terraform scaffolding |
| `src/python_tofu/core/provider.py` | Provider plugin contract and registry |
| `src/python_tofu/providers/gcp/stack.py` | New stack-level fields, backend kinds |
| `src/python_tofu/providers/gcp/quirks.py` | GCP identifier/role/naming rules |
| `src/python_tofu/providers/gcp/limits.py` | Free-tier amounts and measurement |
| `src/python_tofu/providers/gcp/live.py` | Cloud Asset Inventory measurement and rules |
| `src/python_tofu/core/limits.py` | Limit/throttle contract and reports |
| `src/python_tofu/core/runner.py` | New tofu subcommands / flags |
| `src/python_tofu/core/hcl.py` | New HCL constructs |
| `pyproject.toml` | New deps, version bump |
| `flake.nix` | New inputs, checks |
| `nix/module.nix` | New service options |

## Cold (rarely changes)

| File | Rationale |
|------|-----------|
| `src/python_tofu/core/exceptions.py` | Exception hierarchy is stable |
| `src/python_tofu/core/models.py` | `TofuModel` / `BaseStack` envelope is stable |
| `src/python_tofu/core/cli/app.py` | Provider binding is stable |
| `src/python_tofu/core/cli/base.py` | BaseCommand contract is stable |
| `src/python_tofu/core/cli/options.py` | Shared option types are stable |
| `src/python_tofu/models/`, `services/`, `hcl.py`, `loader.py`, `exceptions.py` | Compatibility shims |
| `nix/default.nix` | Package builder is stable |
| `tests/conftest.py` | Fixture contracts are stable |

## Generated / ignored

| Path | Rationale |
|------|-----------|
| `.tofu/` | Rendered HCL + state; ignored via root `.gitignore` |
| `*.tfstate`, `*.tfplan` | Never commit state or plans |
| `result`, `result-*` | Nix build outputs |
