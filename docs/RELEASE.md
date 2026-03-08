# Release Runbook

## Versioning

- Tag format: `vX.Y.Z`
- Keep `project.version` in `pyproject.toml` aligned with release tag.

## Release Validation

Run locally:

```bash
uv sync --group dev
uv run python scripts/check_max_loc.py --max-lines 500
uv run python scripts/run_pytest_gate.py
uv run python scripts/run_mutation_gate.py --python-version 3.11 --retries 1
uv run python -m build
uv run twine check dist/*
```

## GitHub Workflows

- `.github/workflows/ci.yml`: quality, mutation gate, compliance, OTel extras validation, release readiness.
- `.github/workflows/ci.yml` also runs OTLP integration smoke tests on nightly schedule and manual dispatch.
- `.github/workflows/ci.yml` can run OpenObserve end-to-end tests on manual dispatch when `OPENOBSERVE_*` vars/secrets are configured.
- `.github/workflows/release.yml`: build on tags and publish to PyPI on GitHub release publish.

## Local Act Validation

```bash
act -l
act workflow_dispatch -W .github/workflows/ci.yml --container-architecture linux/amd64
```

Prerequisites: run from a git repository checkout and ensure Docker daemon is running.

## Publish Path

1. Push tag `vX.Y.Z`.
2. Create GitHub release from tag.
3. `release.yml` runs build and `twine check`.
4. `publish-pypi` job uploads to PyPI via trusted publisher.
