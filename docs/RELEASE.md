# Release Runbook

## Versioning

- Tag format: `vX.Y.Z`
- Keep `VERSION`, language manifests, exported runtime version constants, and the Go module `VERSION` files (`go/VERSION`, `go/otel/VERSION`) aligned with the release tag.

## Release Notes Checklist

- Document runtime API contract: runtime update/reload mutates internal state only; read the applied snapshot back via the language-specific `get_runtime_config()` / `GetRuntimeConfig()` / `getRuntimeConfig()` accessor.

## Release Validation

Run locally:

```bash
uv sync --group dev
uv run python scripts/check_max_loc.py --max-lines 500
uv run python scripts/run_pytest_gate.py
uv run python scripts/run_mutation_gate.py --python-version 3.11 --retries 1 --min-mutation-score 95
uv run python -m build
uv run twine check dist/*
```

## GitHub Workflows

- `.github/workflows/ci-python.yml`, `ci-typescript.yml`, `ci-go.yml`, and `ci-rust.yml`: language-specific test and quality gates.
- `.github/workflows/ci-spec.yml`, `ci-contracts.yml`, and `ci-surface.yml`: parity, contract, and release-surface gates.
- `.github/workflows/ci-shared.yml`: docs-quality, release-readiness, and optional OpenObserve end-to-end validation.
- `.github/workflows/ci-mutation.yml` and `ci-strip-governance.yml`: mutation and stripped-build safety nets.
- `.github/workflows/release.yml`: build on tags and publish to PyPI on GitHub release publish; also verifies Go consumer resolution after Go tags exist.

Go CI is intentionally split:
- `ci-go.yml` uses an ephemeral `go.work` for pre-release integration of the local `go` and `go/otel` modules.
- `release.yml` runs `GOWORK=off` consumer-mode fetch/build checks after Go tags are pushed, first with `GOPROXY=direct` and then through `proxy.golang.org`.
- Those release checks use generated probe modules that import the tagged Go module like a downstream consumer, instead of trying to run the tagged dependency module's own test suite.
- Go module versions are effectively immutable once `proxy.golang.org` indexes them. If a pushed `go/.../vX.Y.Z` tag points at the wrong commit, force-moving the tag does not repair the proxy view; cut a new Go module version instead.

## Local Act Validation

```bash
scripts/act_local.sh -l
scripts/act_local.sh workflow_dispatch -W .github/workflows/ci-shared.yml --container-architecture linux/amd64
scripts/act_local.sh pull_request -W .github/workflows/ci-go.yml -j workspace-integration --container-architecture linux/amd64
printf '%s\n' '{"ref":"refs/tags/go/otel/v0.4.0","ref_name":"go/otel/v0.4.0"}' > /tmp/act-release-tag.json
scripts/act_local.sh push -W .github/workflows/release.yml -j verify-go-consumer-direct -e /tmp/act-release-tag.json --container-architecture linux/amd64
```

On Apple Silicon, prefer `--container-architecture linux/arm64` for the Go jobs. The local `go test -race` steps can also require a larger Docker memory allocation than the default `act` container budget.

Prerequisites: run from a git repository checkout and ensure Docker daemon is running.

## Local Act Validation (Docker-in-Docker)

When Docker access is proxied through `colima` (macOS) or you need to reuse the host daemon,
configure the socket before running `act`:

```bash
export DOCKER_HOST="unix://${HOME}/.colima/default/docker.sock"
```

Run the `release-readiness` job manually with Docker-in-Docker support:

```bash
scripts/act_local.sh -W .github/workflows/ci-shared.yml workflow_dispatch -j release-readiness \
  --container-architecture linux/amd64 \
  --container-daemon-socket "${DOCKER_HOST}" \
  -P ubuntu-latest=catthehacker/ubuntu:act-latest
```

For jobs that do not require Docker inside the container (for example `docs-quality`), disable
daemon socket bind-mount:

```bash
scripts/act_local.sh -W .github/workflows/ci-shared.yml pull_request -j docs-quality \
  --container-architecture linux/amd64 \
  --container-daemon-socket -
```

Document any socket/mount issues and rerun once host access is restored.

## Publish Path

### Python (PyPI)

1. Push tag `vX.Y.Z`.
2. Create GitHub release from tag.
3. `release.yml` runs build and `twine check`.
4. `publish-pypi` job uploads to PyPI via trusted publisher (OIDC — no token required).

### TypeScript (npm)

Prerequisites (one-time setup):
- Create an `npm` environment in GitHub repo Settings → Environments.
- Add `NPM_TOKEN` as a repository secret (generate at npmjs.com → Access Tokens → Granular).

Release steps:
1. Same tag/release as Python — both publish jobs fire from the same `release.yml`.
2. `build-typescript` job runs `npm ci`, `test:coverage`, and `tsc`; uploads `dist/` artifact.
3. `publish-npm` job downloads the artifact and runs `npm publish --provenance --access public`.

### Go (pkg.go.dev)

Go modules publish automatically when a git tag is pushed — no explicit upload step.

Prerequisites (one-time setup):
- Ensure `go/VERSION`, `go/otel/VERSION`, and `go/CHANGELOG.md` are updated.
- The `go/LICENSE` file must be present at the module root (already committed).

Release steps:
1. Create the Go module tags `go/vX.Y.Z` and `go/otel/vX.Y.Z` from the final release commit.
2. `go get github.com/provide-io/provide-telemetry/go@vX.Y.Z` and `go get github.com/provide-io/provide-telemetry/go/otel@vX.Y.Z` will resolve once the tags are pushed.
3. pkg.go.dev picks up the new versions automatically within a few minutes of the tags being pushed; force a refresh at `https://pkg.go.dev/github.com/provide-io/provide-telemetry/go@vX.Y.Z` if needed.

### Go validation before release

```bash
GOWORK="$(./ci/init-go-workspace.sh "$PWD" /tmp/provide-telemetry-go-work)" go test -race ./go/logger/... ./go/tracer/...
GOWORK="$(./ci/init-go-workspace.sh "$PWD" /tmp/provide-telemetry-go-work)" go test -race ./go/otel
GOWORK="$(./ci/init-go-workspace.sh "$PWD" /tmp/provide-telemetry-go-work)" go build ./go/otel/examples/openobserve/...
cd go
GOWORK=off go build ./...
GOWORK=off go test -race -count=1 -coverprofile=coverage.out .
go tool cover -func=coverage.out | grep total   # must be 100.0%
GOWORK=off go vet ./...
GOWORK=off golangci-lint run
GOWORK=off govulncheck ./...
GOWORK=off gremlins unleash --workers=1 --test-cpu=1 --timeout-coefficient=30 --threshold-efficacy=100 --coverpkg="github.com/provide-io/provide-telemetry/go" --exclude-files="sampling_cmp.go" --exclude-files="resilience_cmp.go" --exclude-files="cmd/e2e_cross_language_client/" --exclude-files="examples/" --exclude-files="internal/" --exclude-files="logger/" --exclude-files="otel/" --exclude-files="scripts/stress/" --exclude-files="tracer/" .
GOWORK=off gremlins unleash --workers=1 --test-cpu=1 --timeout-coefficient=30 --threshold-efficacy=100 ./logger
GOWORK=off gremlins unleash --workers=1 --test-cpu=1 --timeout-coefficient=30 --threshold-efficacy=100 ./tracer
cd otel
GOWORK=off go test -race -coverprofile=coverage.out .
go tool cover -func=coverage.out | grep total   # must be 100.0%
GOWORK=off gremlins unleash --workers=1 --test-cpu=1 --timeout-coefficient=30 --threshold-efficacy=100 --exclude-files="examples/" .
```

### TypeScript validation before release

```bash
cd typescript
npm run lint
npm run format:check
npm run typecheck
npm run test:coverage
npm run build
npm pack --dry-run   # verify tarball contents and size
```
