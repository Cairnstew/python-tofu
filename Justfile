default:
    @just --list

# lint + typecheck + unit/integration tests + flake evaluation
check: lint typecheck test-unit test-integration nix-check

# ruff check and format check
lint:
    ruff check src/ tests/
    ruff format --check src/ tests/

# apply ruff fixes and formatting
lint-fix:
    ruff check --fix src/ tests/
    ruff format src/ tests/

# ruff fixes plus `nix fmt`
fmt: lint-fix fmt-nix

# format .nix files with nixpkgs-fmt
fmt-nix:
    nix fmt

# mypy in strict mode
typecheck:
    mypy src/

# unit tests
test-unit:
    pytest tests/unit/ -v

# CLI subprocess tests
test-integration:
    pytest tests/integration/ -v

# Nix module/home-manager evaluation tests (needs nix in PATH)
test-nix:
    pytest tests/nix_eval/ -v

# every test tier
test:
    pytest -v

# unit tests with a missing-lines report
coverage:
    pytest tests/unit/ --cov --cov-report=term-missing

# evaluate every flake check without building (fast)
nix-check:
    nix flake check --no-build

# build every flake check, same as CI's nix job
nix-check-build:
    nix flake check

# build the application
nix-build:
    nix build .#default

# enter the default dev shell
nix-shell:
    nix develop

# create the org-level seed admin service account (one-time, needs org admin)
bootstrap-admin *ARGS:
    ./scripts/bootstrap-org-admin.sh {{ARGS}}

# pip-audit plus bandit
audit:
    pip-audit
    bandit -r src/ -c pyproject.toml

# regenerate uv.lock from pyproject.toml
uv-lock:
    uv lock

# sync the local .venv (outside the Nix shell)
uv-sync:
    uv sync --all-groups

# upgrade every dependency in uv.lock
uv-upgrade:
    uv lock --upgrade

# build a wheel and sdist with uv
build:
    uv build

# run every pre-commit hook over the tree
pre-commit:
    pre-commit run --all-files

# remove build, cache and bytecode artifacts
clean:
    rm -rf dist/ .mypy_cache/ .ruff_cache/ .cache/
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
