# Release Runbook

## Versioning

- Tag format is per-language: `vX.Y.Z` (Python, root), `typescript/vX.Y.Z`, `rust/vX.Y.Z`,
  `go/vX.Y.Z`, `go/otel/vX.Y.Z`. See "Publish Path" below for what triggers off each.
- `scripts/check_version_sync.py` requires every language's version to share root `VERSION`'s
  major.minor; patch numbers are independent per language and legitimately drift.
- Whichever language you're releasing, its own version file(s) must match the tag you push —
  see the per-language "Release steps" below.

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
- `.github/workflows/release.yml`: publishes each language independently — see "Publish Path" below.

Release publishing is language-scoped, not one joint event. `scripts/check_version_sync.py` only
requires each language's version to share root `VERSION`'s major.minor — patch numbers legitimately
drift per language, so each language publishes off its own trigger:

| Language | Trigger | Requires a GitHub Release? |
|----------|---------|------------------------|
| Python (PyPI) | GitHub Release published (or `workflow_dispatch`) on the root `vX.Y.Z` tag | Yes — root `VERSION` is Python's version |
| TypeScript (npm) | push of a `typescript/vX.Y.Z` tag | No |
| Rust (crates.io) | push of a `rust/vX.Y.Z` tag | No |
| Go (pkg.go.dev) | push of `go/vX.Y.Z` / `go/otel/vX.Y.Z` tags | No |

Cutting a release for one language never touches the others — pushing `typescript/v0.5.2` publishes
npm only; it does not build, test, or publish Python/Rust/Go, and does not require or create a
GitHub Release. Tag only the languages that actually changed.

Go CI is intentionally split the same way:
- `ci-go.yml` uses an ephemeral `go.work` for pre-release integration of the local `go` and `go/otel` modules.
- `release.yml` runs `GOWORK=off` consumer-mode fetch/build checks after Go tags are pushed, first with `GOPROXY=direct` and then through `proxy.golang.org`.
- Those release checks use generated probe modules that import the tagged Go module like a downstream consumer, instead of trying to run the tagged dependency module's own test suite.
- Go module versions are effectively immutable once `proxy.golang.org` indexes them. If a pushed `go/.../vX.Y.Z` tag points at the wrong commit, force-moving the tag does not repair the proxy view; cut a new Go module version instead.
- The same immutability caveat applies to `typescript/vX.Y.Z` and `rust/vX.Y.Z` tags: npm and crates.io both reject republishing an already-used version number, so a wrong tag means cutting a new patch version, not force-moving the tag.

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

Only language released via a GitHub Release object — root `VERSION` is Python's version.

Prerequisites (one-time setup):
- Create `testpypi` and `pypi` environments in GitHub repo Settings → Environments.
- Configure PyPI/TestPyPI Trusted Publishers mapping to this repo + `release.yml` (OIDC — no token needed).

Release steps:
1. Bump root `VERSION` (and `pyproject.toml`'s dynamic pointer stays in sync automatically).
2. Push tag `vX.Y.Z` matching `VERSION`, then create a GitHub Release from it (or use `workflow_dispatch`).
3. `build` job runs `uv build` + `twine check`; `publish-testpypi` uploads to TestPyPI.
4. `verify-testpypi` installs from TestPyPI and asserts `__version__` matches the tag — a mismatch
   between the tag and `VERSION` fails here before anything reaches real PyPI.
5. `publish-pypi` uploads to PyPI via trusted publisher (OIDC).
6. `sign-and-upload` sigstore-signs the wheel/sdist and attaches them + the SBOM to the GitHub Release.

### TypeScript (npm)

Decoupled from Python — no GitHub Release involved, tag push publishes directly.

Prerequisites (one-time setup):
- Create an `npm` environment in GitHub repo Settings → Environments.
- Configure an npm Trusted Publisher on npmjs.com under `@provide-io/telemetry` → Settings →
  Trusted publishers: org=provide-io, repo=provide-telemetry, workflow=release.yml,
  environment=npm (OIDC — no `NPM_TOKEN` secret needed).

Release steps:
1. Bump `typescript/package.json` version, `typescript/src/config.ts`'s `version` export, and
   `typescript/package-lock.json` (run `npm install` in `typescript/` to sync the lockfile) —
   `scripts/check_version_sync.py` checks these three stay in exact 3-way sync with each other,
   and that they share root `VERSION`'s major.minor.
2. Push tag `typescript/vX.Y.Z` matching the bumped `package.json` version.
3. `build-npm` job runs `npm ci`, `vitest run`, `npm run build`, `npm pack`; uploads the tarball
   and a generated SBOM as workflow artifacts.
4. `publish-npm` job downloads the tarball and runs `npm publish --provenance --access public`.

### Rust (crates.io)

Decoupled from Python — no GitHub Release involved, tag push publishes directly.

Prerequisites (one-time setup):
- Create a `crates` environment in GitHub repo Settings → Environments.
- Configure a crates.io Trusted Publisher mapping to this repo + `release.yml` + the `crates`
  environment (OIDC — no `CARGO_REGISTRY_TOKEN` secret needed).

Release steps:
1. Bump `rust/Cargo.toml`'s version to share root `VERSION`'s major.minor.
2. Push tag `rust/vX.Y.Z` matching the bumped `Cargo.toml` version.
3. `build-rust` job runs `cargo test` and `cargo package`; uploads the crate as a workflow artifact.
4. `publish-rust` job runs `cargo publish` via trusted publishing.
5. `cargo publish` has no skip-existing behavior — republishing an already-used version hard-fails
   the job, so `Cargo.toml` must actually change before tagging.

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
