# Enterprise Hardening Design

**Date:** 2026-03-28
**Status:** Draft

## Context

undef-telemetry has strong quality foundations (100% branch coverage, 100% mutation kill, comprehensive pre-commit, strict type checking) but lacks enterprise governance, release automation, and supply chain security. During a recent polyglot infrastructure PR, several pre-existing quality issues on main were discovered — lint errors, type checker failures, formatting drift — despite pre-commit hooks being configured. This indicates gaps between local enforcement and CI enforcement.

## Goals

1. **Zero broken main** — every merge is gated by all quality checks
2. **Automated releases** — conventional commits drive version bumps, changelogs, and publishing
3. **Supply chain hardened** — vulnerability scanning, dependency updates, SBOM, provenance
4. **Operational resilience** — no flaky tests, deterministic CI, pinned dependencies

## Decisions

| Decision | Choice |
|----------|--------|
| Mutation on PRs | Changed-files-only (fast, blocking). Full suite on schedule as safety net. |
| Release automation | release-please (Google) — auto Release PR with version bump + changelog |
| Commit format | Conventional Commits enforced via commitlint |
| Dependency updates | Dependabot (pip, npm, github-actions — weekly) |
| SAST | CodeQL for Python + TypeScript |
| SBOM | CycloneDX attached to GitHub Releases |
| Action pinning | SHA-pinned with version comments |

---

## Phase 1: CI/PR Governance

### CODEOWNERS

Create `.github/CODEOWNERS`:
```
# Default owner for everything
* @tim

# Language-specific owners (expandable as team grows)
/typescript/ @tim
/go/ @tim
/rust/ @tim
/csharp/ @tim

# CI/infrastructure
/.github/ @tim
/spec/ @tim
```

### PR Template

Create `.github/PULL_REQUEST_TEMPLATE.md`:
```markdown
## Summary
<!-- What changed and why -->

## Test Plan
- [ ] Tests pass locally (`uv run python scripts/run_pytest_gate.py`)
- [ ] TypeScript tests pass (`cd typescript && npm run test:coverage`)
- [ ] Lint/type checks clean

## Breaking Changes
<!-- List any breaking changes, or "None" -->
```

### Branch Protection

Document configuration for GitHub UI (or apply via `gh api`):
- **Required reviews:** 1
- **Required status checks:**
  - `quality (3.11)` (from ci-python.yml)
  - `typescript-quality` (from ci-typescript.yml)
  - `docs-quality` (from ci-shared.yml)
  - `conformance` (from ci-spec.yml)
  - `version-sync` (from ci-spec.yml)
  - `mutation-pr` (new — changed-files mutation check)
- **Require branches up-to-date:** yes
- **Dismiss stale reviews:** yes
- **No direct pushes to main**

### Changed-Files Mutation Gate

Add a new job `mutation-pr` to `ci-python.yml` that:
1. Uses `git diff --name-only origin/main...HEAD -- 'src/**/*.py'` to find changed source files
2. Runs `mutmut run` scoped to only those files
3. Requires 100% kill score on changed files
4. Runs on `pull_request` events (not just schedule)

For TypeScript, add `typescript-mutation-pr` to `ci-typescript.yml`:
1. Uses Stryker's `--mutate` flag to scope to changed files
2. Requires 100% kill score on changed files
3. Runs on `pull_request` events

---

## Phase 2: Automated Release Pipeline

### Conventional Commits

**Enforce via commitlint:**
- Add `commitlint.config.js` at repo root
- Allowed prefixes: `feat`, `fix`, `test`, `ci`, `docs`, `refactor`, `style`, `chore`, `perf`, `build`
- Scope optional: `feat(typescript):`, `fix(spec):`
- Breaking changes: `feat!:` or `BREAKING CHANGE:` footer

**Enforcement points:**
- Pre-commit hook on `commit-msg` stage (local, using `commitlint` via npx)
- CI check on every commit in the PR (not just PR title — ensures full history is clean)

### release-please

**Configuration:** `.release-please-config.json` + `.release-please-manifest.json`

release-please supports monorepo with multiple packages:
- **Python package** — path `.`, version in `VERSION`
- **TypeScript package** — path `typescript/`, version in `typescript/package.json`

**Workflow:** `.github/workflows/release-please.yml`
```yaml
on:
  push:
    branches: [main]

jobs:
  release-please:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: googleapis/release-please-action@v4
        with:
          config-file: .release-please-config.json
          manifest-file: .release-please-manifest.json
```

**Release flow:**
1. Conventional commits merge to main
2. release-please opens/updates a Release PR with bumped versions + changelog
3. Maintainer merges the Release PR
4. release-please creates GitHub Release + tag
5. Existing `release.yml` triggers on tag → publishes to PyPI + npm

### Changelog

`CHANGELOG.md` is managed by release-please. Existing entries are preserved; new entries are appended automatically from conventional commits.

---

## Phase 3: Supply Chain Security

### Dependabot

Create `.github/dependabot.yml`:
```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
    groups:
      minor-and-patch:
        update-types: [minor, patch]

  - package-ecosystem: npm
    directory: /typescript
    schedule:
      interval: weekly
    groups:
      minor-and-patch:
        update-types: [minor, patch]

  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
    groups:
      actions:
        patterns: ["*"]
```

Groups reduce PR noise — minor/patch updates are batched into a single PR per ecosystem.

### CodeQL

Create `.github/workflows/codeql.yml`:
- Runs on push to main + PRs
- Analyzes Python and TypeScript/JavaScript
- Uses default CodeQL query suites (security-extended)

### SBOM Generation

Add to `release.yml`:
- Python: `cyclonedx-py` generates CycloneDX SBOM from installed packages
- TypeScript: `@cyclonedx/cyclonedx-npm` generates SBOM from package-lock.json
- Both SBOMs attached as release artifacts

### Artifact Signing

- npm: Already uses `--provenance` (SLSA Build L3)
- PyPI: Already uses OIDC trusted publishing
- Additionally: Sign release artifacts with Sigstore cosign in `release.yml`
  - `cosign sign-blob` on wheel, tarball, and SBOM files
  - Attach `.sig` files as release artifacts

---

## Phase 4: Operational Hardening

### Pin GitHub Actions by SHA

Replace all `@v6`, `@v7`, `@v8` references with full SHA + version comment:
```yaml
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v6.0.2
```

This prevents supply chain attacks via tag mutation (a compromised action could replace what `@v6` points to).

Apply to all workflow files: `ci-python.yml`, `ci-typescript.yml`, `ci-shared.yml`, `ci-spec.yml`, `release.yml`.

### Flaky Test Strategy

Replace the loosened `MAX_EVENT_NAME_NS = 25_000` threshold with proper flaky test handling:
- Add `pytest-rerunfailures` to dev dependencies
- Mark timing-sensitive tests with `@pytest.mark.flaky(reruns=2)`
- Restore the original tight threshold (10μs) with reruns as safety net
- CI reports rerun count — if a test consistently reruns, it signals a real regression

### CI Caching

Current state: uv cache and npm cache are configured. Verify:
- uv cache key includes `uv.lock` hash
- npm cache key includes `package-lock.json` hash
- Add pip cache for `pip-audit` step if not already cached

---

## Implementation Order

Each phase is independent and can be implemented in any order. Recommended sequence:

1. **Phase 1** (CI/PR Governance) — immediate impact, prevents broken main
2. **Phase 2** (Release Pipeline) — enables sustainable release cadence
3. **Phase 3** (Supply Chain) — required for enterprise consumers
4. **Phase 4** (Operational) — polish and resilience

Total: ~15-20 tasks across all 4 phases.

## Verification

- Phase 1: Create a test PR, verify all required checks run and block merge
- Phase 2: Make a `feat:` commit, verify release-please opens a Release PR
- Phase 3: Verify Dependabot creates PRs, CodeQL runs on PR, SBOM attached to test release
- Phase 4: Verify SHA-pinned actions resolve correctly, flaky tests rerun instead of failing
