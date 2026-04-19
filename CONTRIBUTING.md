<!-- SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc -->

<!-- SPDX-License-Identifier: Apache-2.0 -->

# Contributing to provide-telemetry

## Prerequisites

- **Python**: [uv](https://docs.astral.sh/uv/) (manages Python versions and virtualenvs)
- **TypeScript**: Node.js 22+, npm
- **Docker** (for local OpenObserve stack)

## Setup

### Python

```bash
uv sync --group dev                   # Base dev deps
uv sync --group dev --extra otel      # Include OpenTelemetry extras
```

### TypeScript

```bash
cd typescript
npm install
```

## Running tests

### Python

```bash
uv run python scripts/run_pytest_gate.py                  # Full suite (100% branch coverage enforced)
uv run python scripts/run_pytest_gate.py -k "test_name"   # Single test
uv run python scripts/run_pytest_gate.py -m otel --no-cov # OTel-specific tests
```

### TypeScript

```bash
cd typescript
npm test              # Full suite
npm run test:coverage # With coverage report
```

Both languages enforce **100% branch coverage**.

## Code style

### Python

```bash
uv run ruff format --check .   # Formatting
uv run ruff check .            # Linting
uv run mypy src tests          # Type checking (strict mode)
```

### TypeScript

```bash
cd typescript
npx eslint .
npx prettier --check .
```

## Quality gates

Every PR must pass these gates in CI:

| Gate             | Command                                                                           |
| ---------------- | --------------------------------------------------------------------------------- |
| Mutation testing | `uv run python scripts/run_mutation_gate.py` — 100% kill score required           |
| SPDX headers     | `uv run python scripts/check_spdx_headers.py` — Apache-2.0 on all source files    |
| Spelling         | `uv run codespell`                                                                |
| Security scan    | `uv run bandit -r src -ll`                                                        |
| Max LOC          | `uv run python scripts/check_max_loc.py --max-lines 500` — no file over 500 lines |

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
1. Ensure all CI gates pass (coverage, mutation, lint, SPDX, codespell, bandit).
1. Keep language parity -- changes to the API surface must be reflected in both Python and TypeScript per `spec/telemetry-api.yaml`.
1. Request review. Squash-merge when approved.

## Adding a new feature

1. Update `spec/telemetry-api.yaml` with the new API surface.
1. Implement in Python (`src/provide/telemetry/`) with tests in `tests/`.
1. Implement in TypeScript (`typescript/src/`) with tests in `typescript/test/`.
1. Run conformance validation: `uv run python spec/validate_conformance.py`.
1. Ensure both languages pass all quality gates before opening a PR.

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
