default:
    @just --list

check: lint typecheck test-unit nix-check

lint:
    ruff check src/ tests/
    ruff format --check src/ tests/

lint-fix:
    ruff check --fix src/ tests/
    ruff format src/ tests/

typecheck:
    mypy src/

test-unit:
    pytest tests/unit/ -v

test-integration:
    pytest tests/integration/ -v

test:
    pytest -v

nix-check:
    nix flake check --no-build

nix-build:
    nix build .#default

build:
    uv build

clean:
    rm -rf dist/ .mypy_cache/ .ruff_cache/
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

uv-lock:
    uv lock

uv-sync:
    uv sync --all-groups

uv-upgrade:
    uv lock --upgrade
