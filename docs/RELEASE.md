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

## Local Act Validation (Docker-in-Docker)

When Docker access is proxied through `colima` (macOS) or you need to reuse the host daemon,
configure the socket before running `act`:

```bash
export DOCKER_HOST=unix:///REDACTED_ABS_PATH
```

Run the quality job manually with Docker-in-Docker support:

```bash
act -W .github/workflows/ci.yml workflow_dispatch -j quality \
  --container-architecture linux/amd64 \
  --container-daemon-socket "${DOCKER_HOST}" \
  -P ubuntu-latest=catthehacker/ubuntu:act-latest
```

If you run `act` frequently, extend `.actrc` with the same options so every invocation reuses the
configured socket and image. Document any socket/mount issues and rerun once host access is restored.

## Publish Path

1. Push tag `vX.Y.Z`.
2. Create GitHub release from tag.
3. `release.yml` runs build and `twine check`.
4. `publish-pypi` job uploads to PyPI via trusted publisher.
