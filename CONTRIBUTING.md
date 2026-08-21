# Contributing to provide-telemetry

## Prerequisites

- **Python**: [uv](https://docs.astral.sh/uv/) (manages Python versions and virtualenvs)
- **TypeScript**: Node.js 22+, npm
- **Go**: Go 1.26+
- **Rust**: stable toolchain via rustup
- **C#**: .NET SDK 10
- **Docker** (for local OpenObserve stack)

Only the languages you touch need their toolchains installed; CI runs all five.

## Setup

```bash
uv sync --group dev                   # Python base dev deps
uv sync --group dev --extra otel      # Include OpenTelemetry extras
cd typescript && npm install          # TypeScript
```

Go, Rust, and C# resolve their dependencies on first build (`go build`,
`cargo build`, `dotnet build`).

## Running tests

```bash
uv run python scripts/run_pytest_gate.py                  # Python (100% branch coverage enforced)
uv run python scripts/run_pytest_gate.py -k "test_name"   # Single test
uv run python scripts/run_pytest_gate.py -m otel --no-cov # OTel-specific tests
cd typescript && npm test                                 # TypeScript
cd go && go test ./... && cd otel && go test ./...        # Go (both modules)
cargo test --manifest-path rust/Cargo.toml --all-features # Rust
cd csharp && dotnet test                                  # C#
```

Python, TypeScript, and Go enforce **100% branch coverage**; Rust enforces
100% covered functions and zero uncovered lines via `cargo llvm-cov`; C#
enforces ratcheted floors (99% line / 97% branch) in `ci-csharp.yml`.

## Code style

```bash
uv run ruff format --check . && uv run ruff check .   # Python format + lint
uv run mypy src tests                                 # Python types (strict)
cd typescript && npx eslint . && npx prettier --check .
gofmt -l go/ && go vet ./...                          # Go (run inside go/)
cargo clippy --manifest-path rust/Cargo.toml --all-features
cd csharp && dotnet format --verify-no-changes
```

## Quality gates

Every PR must pass these gates in CI:

| Gate | Command |
|------|---------|
| Mutation testing | `uv run python scripts/run_mutation_gate.py --min-mutation-score 95` — zero survivors in Python (mutmut), Go (gremlins, six package surfaces) and Rust (cargo-mutants). TypeScript (Stryker) breaks below 95 core / 80 OTLP and currently measures 100%; C# (Stryker.NET) breaks below 85 against a measured baseline — see `csharp/stryker-config.json` for what survives and why |
| SPDX headers | `uv run python scripts/check_spdx_headers.py` — Apache-2.0 on all Python, Go, Rust, and C# sources (TypeScript is checked in `ci-typescript.yml`) |
| REUSE compliance | `uvx reuse lint` — every file carries or is annotated with licensing info |
| Spelling | `uv run codespell` |
| Security scan | `uv run bandit -r src -ll` |
| Dependency audit | `uv run python -m pip_audit --path .` |
| Max LOC | `uv run python scripts/check_max_loc.py --max-lines 777` — no source file over 777 lines |
| Version sync | `uv run python scripts/check_version_sync.py` — all languages share `VERSION`'s major.minor |
| Docs accuracy | `uv run python scripts/check_docs_accuracy.py` — documented claims must match the tree |

## SPDX policy

Python files must start with:

1. optional shebang
2. `SPDX-FileCopyrightText`
3. `SPDX-License-Identifier`
4. `SPDX-Comment`
5. `#` separator line
6. blank line

Go, Rust, and C# files start with the same block in `//` comments (first two
lines checked). Use `uv run python scripts/normalize_spdx_headers.py` to
auto-fix and `uv run python scripts/check_spdx_headers.py` to validate.
Markdown files carry no SPDX headers; they are covered by `REUSE.toml`
annotations instead.

## Commit message format

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add sampling rate config to TypeScript client
fix: prevent double-init when setup called concurrently
docs: update React integration examples
refactor: extract PII rule engine into dedicated module
```

## PR process

1. Branch from `main`.
2. Ensure all CI gates pass (coverage, mutation, lint, SPDX, codespell, bandit).
3. Keep language parity — changes to the API surface must be reflected in all
   five languages per `spec/telemetry-api.yaml`, or the spec's applicability
   lists must record why a language is exempt.
4. Request review. Squash-merge when approved.

## Adding a new feature

1. Update `spec/telemetry-api.yaml` with the new API surface.
2. Implement in Python (`src/provide/telemetry/`) first — Python is the
   behavioral reference — with tests in `tests/`.
3. Implement in TypeScript (`typescript/src/`), Go (`go/`), Rust (`rust/src/`),
   and C# (`csharp/src/`), each with tests.
4. Add or extend shared fixtures in `spec/` so the behavior is pinned in every
   language, and register test IDs in `spec/fixture_test_ids.yaml`.
5. Run conformance validation: `uv run python spec/validate_conformance.py`.
6. Ensure all languages pass their quality gates before opening a PR.

## Running OpenObserve locally

The repo includes a script to spin up a full local telemetry stack (OpenObserve + collectors):

```bash
./scripts/start-telemetry-stack.sh
```

E2E tests require the stack to be running and these env vars set:

```bash
export OPENOBSERVE_USER="admin@provide.test"
export OPENOBSERVE_PASSWORD="Complexpass#123"  # pragma: allowlist secret
export OPENOBSERVE_URL="http://localhost:5080"
uv run python scripts/run_pytest_gate.py -m e2e --no-cov
```
