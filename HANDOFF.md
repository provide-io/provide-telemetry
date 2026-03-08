# HANDOFF

SPDX-License-Identifier: Apache-2.0  
SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC

## Operator Checklist

1. Use the real `undef-telemetry` git checkout (must include `.git`).
2. Apply/sync these file changes into that checkout.
3. Run:
   - `uv sync --group dev`
   - `pre-commit run --all-files`
   - `uv run pytest`
   - `uv sync --group dev --extra otel && uv run pytest -m otel --no-cov -q`
   - `OPENOBSERVE_URL=http://localhost:5080/api/default OPENOBSERVE_USER=user@example.com OPENOBSERVE_PASSWORD=password uv run pytest -m e2e --no-cov -q`
   - `uv run python scripts/run_mutation_gate.py --python-version 3.11 --max-children 4 --retries 1`
   - `act -W .github/workflows/ci.yml workflow_dispatch -j quality --container-architecture linux/amd64`
4. Build/release readiness:
   - `uv run python -m build`
   - `uv run twine check dist/*`
5. Commit and push.

## Snapshot (March 7, 2026)

- Scope: `undef-telemetry` hardening for strict quality/compliance/release workflow.
- Status: code changes are complete on disk but **not committed** (directory is not a git repo checkout).
- Python target: 3.11+ only.

## What Was Implemented

- Strict pre-commit updates:
  - Added `max-loc`, `pytest`, and manual `mutation-gate` hooks.
- CI updates:
  - Added max LOC check to quality job.
  - Added dedicated mutation-gate job.
  - Matrix remains Python 3.11 -> 3.14.
- Tooling scripts:
  - `scripts/check_max_loc.py`
  - `scripts/run_mutation_gate.py`
  - `scripts/_mutmut_shims/setproctitle.py` (no-op shim used only during mutmut runs)
  - `scripts/__init__.py`
- Test structure and stability:
  - Tests are split by feature directories.
  - Added `tests/conftest.py` for consistent local imports.
  - Added/updated tooling tests under `tests/tooling/`.
  - Added `tooling` marker and excluded tooling tests from mutmut test selection.
- Docs/runbooks updated:
  - `README.md`, `docs/OPERATIONS.md`, `docs/RELEASE.md`.
- Compliance config updated:
  - `REUSE.toml` annotations expanded for generated/cache paths.

## Validation Results (Local)

Passed:

- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run mypy src tests`
- `uv run ty check src tests`
- `uv run bandit -r src -ll`
- `uv run python scripts/check_max_loc.py --max-lines 500`
- `uv run pytest` (100% coverage)
- `uv sync --group dev --extra otel && uv run pytest -m otel --no-cov -q`
- `OPENOBSERVE_URL=http://localhost:5080/api/default OPENOBSERVE_USER=user@example.com OPENOBSERVE_PASSWORD=password uv run pytest -m e2e --no-cov -q`
- `uv run python -m build`
- `uv run twine check dist/*`
- `uv run python scripts/run_mutation_gate.py --python-version 3.11 --max-children 1 --retries 0 --min-mutation-score 1`
- `uv run python scripts/run_mutation_gate.py --python-version 3.11 --max-children 4 --retries 0 --min-mutation-score 1`
- `uvx reuse lint` passes in a clean copy that excludes runtime artifacts (`.venv`, caches, `mutants`, `dist`, `build`).

## Known Blockers

1. `act` verification is currently blocked in this environment because:
   - Current directory is not a git checkout (`.git` missing).
   - Docker daemon is unavailable.
2. `pre-commit run --all-files` is blocked outside a git repo.

## Next Actions (Required)

1. Move/apply this tree into the actual git checkout of `undef-telemetry`.
2. Commit all changed files.
3. Re-run in repo context:
   - `pre-commit run --all-files`
   - `act -W .github/workflows/ci.yml workflow_dispatch -j quality --container-architecture linux/amd64`
4. Keep using `scripts/run_mutation_gate.py` (it now injects a no-op `setproctitle` shim via `PYTHONPATH` for mutmut subprocesses to avoid observed segfault behavior).

## Changed Files (High-Level)

- `.pre-commit-config.yaml`
- `.github/workflows/ci.yml`
- `README.md`
- `docs/OPERATIONS.md`
- `docs/RELEASE.md`
- `pyproject.toml`
- `REUSE.toml`
- `scripts/__init__.py`
- `scripts/check_max_loc.py`
- `scripts/run_mutation_gate.py`
- `scripts/_mutmut_shims/setproctitle.py`
- `tests/conftest.py`
- `tests/tooling/test_check_max_loc.py`
- `tests/tooling/test_run_mutation_gate.py`
- plus test file relocations into feature directories completed during this implementation cycle.
