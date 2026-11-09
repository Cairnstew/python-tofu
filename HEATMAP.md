# Change Heatmap

## Hot (changes every feature)

| File | Rationale |
|------|-----------|
| `src/python_tofu/models/gcp.py` | New GCP resource types and fields |
| `src/python_tofu/services/renderer.py` | New resource → HCL mappings |
| `src/python_tofu/cli/commands/` | New commands and options |
| `examples/gcp_bootstrap/infra.py` | Living example / integration surface |
| `.github/workflows/ci.yml` | Path filters |

## Warm (changes per major version)

| File | Rationale |
|------|-----------|
| `src/python_tofu/models/stack.py` | New stack-level fields, backend kinds |
| `src/python_tofu/services/runner.py` | New tofu subcommands / flags |
| `src/python_tofu/hcl.py` | New HCL constructs |
| `pyproject.toml` | New deps, version bump |
| `flake.nix` | New inputs, checks |
| `nix/module.nix` | New service options |

## Cold (rarely changes)

| File | Rationale |
|------|-----------|
| `src/python_tofu/exceptions.py` | Exception hierarchy is stable |
| `src/python_tofu/cli/commands/base.py` | BaseCommand contract is stable |
| `src/python_tofu/cli/options.py` | Shared option types are stable |
| `nix/default.nix` | Package builder is stable |
| `tests/conftest.py` | Fixture contracts are stable |

## Generated / ignored

| Path | Rationale |
|------|-----------|
| `.tofu/` | Rendered HCL + state; ignored via root `.gitignore` |
| `*.tfstate`, `*.tfplan` | Never commit state or plans |
| `result`, `result-*` | Nix build outputs |
