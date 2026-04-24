# Go CI Workspace Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split Go verification into pre-release source-based workspace integration and post-tag consumer-resolution checks.

**Architecture:** Generate an ephemeral `go.work` file outside the repository checkout so CI can test the unreleased Go modules together without committing workspace state. Keep external-consumer verification in the release workflow with `GOWORK=off`, using direct fetch first and proxy verification second.

**Tech Stack:** GitHub Actions, Go workspaces, `act`, shell helpers

---

### Task 1: Add an Ephemeral Go Workspace Helper

**Files:**
- Create: `ci/init-go-workspace.sh`
- Test: local shell invocation from the repository root

- [ ] **Step 1: Add the workspace helper script**

```bash
#!/usr/bin/env bash
set -euo pipefail

repo_root="${1:?repository root required}"
workspace_dir="${2:?workspace output directory required}"

mkdir -p "${workspace_dir}"
rm -f "${workspace_dir}/go.work" "${workspace_dir}/go.work.sum"

go work init \
  "${repo_root}/go" \
  "${repo_root}/go/internal" \
  "${repo_root}/go/logger" \
  "${repo_root}/go/tracer"

mv go.work "${workspace_dir}/go.work"
if [ -f go.work.sum ]; then
  mv go.work.sum "${workspace_dir}/go.work.sum"
fi

printf '%s\n' "${workspace_dir}/go.work"
```

- [ ] **Step 2: Make the helper executable**

Run: `chmod +x ci/init-go-workspace.sh`
Expected: exit code `0`

- [ ] **Step 3: Verify the helper returns a usable workfile**

Run: `WORKFILE=$(./ci/init-go-workspace.sh "$PWD" /tmp/provide-telemetry-go-work) && test -f "$WORKFILE"`
Expected: exit code `0`

### Task 2: Split Go CI Into Standalone and Workspace Paths

**Files:**
- Modify: `.github/workflows/ci-go.yml`
- Test: `act -W .github/workflows/ci-go.yml pull_request -j workspace-integration`

- [ ] **Step 1: Force standalone jobs out of workspace mode**

Add workflow-level environment:

```yaml
env:
  GOWORK: off
```

- [ ] **Step 2: Add a dedicated workspace integration job**

Add a job that:

```yaml
workspace-integration:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@...
    - uses: actions/setup-go@...
      with:
        go-version: "1.26"
    - name: Generate temporary go.work
      run: |
        WORKFILE="$(./ci/init-go-workspace.sh "$GITHUB_WORKSPACE" "$RUNNER_TEMP/provide-telemetry-go-work")"
        echo "GOWORK=${WORKFILE}" >> "$GITHUB_ENV"
        go env GOWORK
    - name: Run go/logger tests with coverage
      working-directory: go/logger
      run: go test -race -coverprofile=coverage.out ./...
    - name: Enforce go/logger 100% coverage
      working-directory: go/logger
      run: |
        TOTAL=$(go tool cover -func=coverage.out | grep total | awk '{print $3}')
        test "$TOTAL" = "100.0%"
    - name: Run go/tracer tests
      working-directory: go/tracer
      run: go test -race ./...
```

- [ ] **Step 3: Remove standalone submodule jobs that depend on unpublished tags**

Delete `test-logger` and `test-tracer` from `ci-go.yml` after their checks move into `workspace-integration`.

- [ ] **Step 4: Verify the workflow locally**

Run: `act -W .github/workflows/ci-go.yml pull_request -j workspace-integration --container-architecture linux/amd64`
Expected: the job completes successfully with local source resolution.

### Task 3: Move Consumer-Mode Resolution Checks Into Release

**Files:**
- Modify: `.github/workflows/release.yml`
- Modify: `docs/RELEASE.md`
- Test: `act -W .github/workflows/release.yml push -j verify-go-consumer-direct -e /tmp/act-release-tag.json`

- [ ] **Step 1: Expand Go tag triggers in `release.yml`**

Add tag patterns:

```yaml
tags:
  - 'go/v*'
  - 'go/internal/v*'
  - 'go/logger/v*'
  - 'go/tracer/v*'
```

- [ ] **Step 2: Add direct consumer-resolution verification**

Create a job that runs with:

```yaml
env:
  GOWORK: off
  GOPROXY: direct
  GOSUMDB: off
  GONOSUMDB: github.com/provide-io/provide-telemetry
```

and verifies:

```bash
cd "$(mktemp -d)"
go mod init probe
go get "${MODULE}@${VERSION}"
go test "${MODULE}/..."
```

- [ ] **Step 3: Keep proxy verification as a separate release-stage signal**

After polling `proxy.golang.org`, rerun:

```bash
cd "$(mktemp -d)"
go mod init probe
go get "${MODULE}@${VERSION}"
go test "${MODULE}/..."
```

- [ ] **Step 4: Update the release runbook**

Document that `ci-go.yml` validates unpublished Go modules via an ephemeral workspace and `release.yml` validates consumer resolution after tags exist.

- [ ] **Step 5: Verify the release consumer job locally**

Run: `printf '%s\n' '{"ref":"refs/tags/go/logger/v0.4.0","ref_name":"go/logger/v0.4.0"}' > /tmp/act-release-tag.json`
Expected: the event payload file exists.

- [ ] **Step 6: Run the release consumer job with the tag payload**

Run: `act -W .github/workflows/release.yml push -j verify-go-consumer-direct -e /tmp/act-release-tag.json --container-architecture linux/amd64`
Expected: the consumer-mode job runs in `GOWORK=off` and reaches the fetch/build validation steps.
