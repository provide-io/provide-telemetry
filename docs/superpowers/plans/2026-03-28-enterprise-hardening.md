# Enterprise Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add enterprise governance, automated releases, supply chain security, and operational hardening to undef-telemetry.

**Architecture:** Four independent phases: (1) CI/PR governance with branch protection and changed-files mutation gates, (2) release-please with conventional commits, (3) Dependabot + CodeQL + SBOM + signing, (4) SHA-pinned actions + flaky test handling.

**Tech Stack:** GitHub Actions, release-please, commitlint, Dependabot, CodeQL, CycloneDX, Sigstore cosign, pytest-rerunfailures

---

## Phase 1: CI/PR Governance

### Task 1: Create CODEOWNERS

**Files:**
- Create: `.github/CODEOWNERS`

- [ ] **Step 1: Create the CODEOWNERS file**

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

- [ ] **Step 2: Commit**

```bash
git add .github/CODEOWNERS
git commit -m "ci: add CODEOWNERS for code review assignment"
```

---

### Task 2: Create PR template

**Files:**
- Create: `.github/PULL_REQUEST_TEMPLATE.md`

- [ ] **Step 1: Create the PR template**

```markdown
## Summary
<!-- What changed and why -->

## Test Plan
- [ ] Tests pass locally (`uv run python scripts/run_pytest_gate.py`)
- [ ] TypeScript tests pass (`cd typescript && npm run test:coverage`)
- [ ] Lint/type checks clean (`uv run ruff check . && uv run mypy src tests && uv run ty check src tests`)

## Breaking Changes
<!-- List any breaking changes, or "None" -->
None
```

- [ ] **Step 2: Commit**

```bash
git add .github/PULL_REQUEST_TEMPLATE.md
git commit -m "ci: add pull request template"
```

---

### Task 3: Add changed-files Python mutation gate to PRs

**Files:**
- Modify: `.github/workflows/ci-python.yml`

- [ ] **Step 1: Add the mutation-pr job**

Add this job after the existing `mutation-gate` job in `.github/workflows/ci-python.yml`:

```yaml
  mutation-pr:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v7
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
      - run: uv sync --group dev
      - name: Find changed source files
        id: changed
        run: |
          files=$(git diff --name-only origin/main...HEAD -- 'src/**/*.py' | tr '\n' ' ')
          echo "files=$files" >> "$GITHUB_OUTPUT"
          if [ -z "$files" ]; then
            echo "skip=true" >> "$GITHUB_OUTPUT"
          else
            echo "skip=false" >> "$GITHUB_OUTPUT"
          fi
      - name: Run mutation testing on changed files
        if: steps.changed.outputs.skip == 'false'
        run: |
          uv run mutmut run ${{ steps.changed.outputs.files }} \
            --CI \
            --no-progress
        env:
          MUTMUT_RUNNER: "uv run pytest -x -o addopts= --no-cov -m 'not integration and not e2e and not otel and not tooling and not memray'"
      - name: Check mutation score
        if: steps.changed.outputs.skip == 'false'
        run: |
          result=$(uv run mutmut results)
          if echo "$result" | grep -q "survived"; then
            echo "::error::Surviving mutants found in changed files"
            echo "$result" | grep "survived"
            exit 1
          fi
          echo "All mutants killed in changed files"
```

- [ ] **Step 2: Verify YAML syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci-python.yml'))"
```

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci-python.yml
git commit -m "ci: add changed-files mutation gate for Python PRs"
```

---

### Task 4: Add changed-files TypeScript mutation gate to PRs

**Files:**
- Modify: `.github/workflows/ci-typescript.yml`

- [ ] **Step 1: Add the typescript-mutation-pr job**

Add this job after the existing `typescript-mutation-gate` job in `.github/workflows/ci-typescript.yml`:

```yaml
  typescript-mutation-pr:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    defaults:
      run:
        working-directory: typescript
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - uses: actions/setup-node@v6
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: typescript/package-lock.json
      - run: npm ci
      - name: Find changed source files
        id: changed
        run: |
          files=$(git diff --name-only origin/main...HEAD -- 'typescript/src/**/*.ts' | sed 's|^typescript/||' | tr '\n' ',')
          echo "files=$files" >> "$GITHUB_OUTPUT"
          if [ -z "$files" ]; then
            echo "skip=true" >> "$GITHUB_OUTPUT"
          else
            echo "skip=false" >> "$GITHUB_OUTPUT"
          fi
      - name: Run mutation testing on changed files
        if: steps.changed.outputs.skip == 'false'
        run: npx stryker run --mutate "${{ steps.changed.outputs.files }}"
```

- [ ] **Step 2: Verify YAML syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci-typescript.yml'))"
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci-typescript.yml
git commit -m "ci: add changed-files mutation gate for TypeScript PRs"
```

---

### Task 5: Document branch protection rules

**Files:**
- Create: `docs/BRANCH_PROTECTION.md`

- [ ] **Step 1: Create the branch protection documentation**

```markdown
# Branch Protection Configuration

Apply these settings in GitHub → Settings → Branches → Branch protection rules → `main`:

## Required Settings

- **Require a pull request before merging**
  - Required approving reviews: 1
  - Dismiss stale pull request approvals when new commits are pushed: yes
- **Require status checks to pass before merging**
  - Require branches to be up to date before merging: yes
  - Required checks:
    - `quality (3.11)` (CI — Python)
    - `typescript-quality` (CI — TypeScript)
    - `docs-quality` (CI — Shared)
    - `conformance` (Spec Conformance)
    - `version-sync` (Spec Conformance)
    - `mutation-pr` (CI — Python, PR only)
    - `typescript-mutation-pr` (CI — TypeScript, PR only)
- **Do not allow bypassing the above settings**

## Apply via CLI

```bash
gh api repos/undef-games/undef-telemetry/branches/main/protection \
  --method PUT \
  --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "quality (3.11)",
      "typescript-quality",
      "docs-quality",
      "conformance",
      "version-sync",
      "mutation-pr",
      "typescript-mutation-pr"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "required_approving_review_count": 1
  },
  "restrictions": null
}
EOF
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/BRANCH_PROTECTION.md
git commit -m "docs: add branch protection configuration guide"
```

---

## Phase 2: Automated Release Pipeline

### Task 6: Add commitlint

**Files:**
- Create: `commitlint.config.js`
- Modify: `.pre-commit-config.yaml`

- [ ] **Step 1: Create commitlint config**

```javascript
// SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
// SPDX-License-Identifier: Apache-2.0

export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [
      2,
      'always',
      ['feat', 'fix', 'test', 'ci', 'docs', 'refactor', 'style', 'chore', 'perf', 'build'],
    ],
    'subject-case': [0],
    'body-max-line-length': [0],
  },
};
```

- [ ] **Step 2: Install commitlint as a dev dependency**

```bash
npm install --save-dev @commitlint/cli @commitlint/config-conventional --prefix .
```

Note: This creates a root-level `package.json` for commitlint only. Alternatively, install globally in CI.

Actually, a simpler approach: use `npx` in the pre-commit hook — no install needed.

- [ ] **Step 3: Add commitlint hook to pre-commit**

Add this to `.pre-commit-config.yaml` after the `codespell` repo:

```yaml
  - repo: https://github.com/alessandrojcm/commitlint-pre-commit-hook
    rev: v9.18.0
    hooks:
      - id: commitlint
        stages: [commit-msg]
        additional_dependencies: ['@commitlint/config-conventional']
```

- [ ] **Step 4: Test the hook locally**

```bash
echo "bad commit message" | npx commitlint
```

Expected: Error — "type may not be empty"

```bash
echo "feat: add commitlint" | npx commitlint
```

Expected: Pass

- [ ] **Step 5: Commit**

```bash
git add commitlint.config.js .pre-commit-config.yaml
git commit -m "ci: add commitlint for conventional commit enforcement"
```

---

### Task 7: Configure release-please

**Files:**
- Create: `.release-please-config.json`
- Create: `.release-please-manifest.json`
- Create: `.github/workflows/release-please.yml`

- [ ] **Step 1: Create release-please config**

Create `.release-please-config.json`:

```json
{
  "$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
  "packages": {
    ".": {
      "release-type": "python",
      "package-name": "undef-telemetry",
      "extra-files": ["VERSION"],
      "changelog-path": "CHANGELOG.md"
    },
    "typescript": {
      "release-type": "node",
      "package-name": "@undef/telemetry",
      "changelog-path": "CHANGELOG.md"
    }
  },
  "separate-pull-requests": false,
  "group-pull-request-title-pattern": "chore: release ${version}",
  "changelog-sections": [
    {"type": "feat", "section": "Features"},
    {"type": "fix", "section": "Bug Fixes"},
    {"type": "perf", "section": "Performance"},
    {"type": "test", "section": "Tests"},
    {"type": "ci", "section": "CI/CD"},
    {"type": "docs", "section": "Documentation"},
    {"type": "refactor", "section": "Refactoring"},
    {"type": "chore", "section": "Maintenance", "hidden": true}
  ]
}
```

- [ ] **Step 2: Create the manifest (current versions)**

Create `.release-please-manifest.json`:

```json
{
  ".": "0.3.0",
  "typescript": "0.3.0"
}
```

- [ ] **Step 3: Create the release-please workflow**

Create `.github/workflows/release-please.yml`:

```yaml
name: Release Please

on:
  push:
    branches: [main]

permissions:
  contents: write
  pull-requests: write

jobs:
  release-please:
    runs-on: ubuntu-latest
    steps:
      - uses: googleapis/release-please-action@v4
        with:
          config-file: .release-please-config.json
          manifest-file: .release-please-manifest.json
```

- [ ] **Step 4: Commit**

```bash
git add .release-please-config.json .release-please-manifest.json .github/workflows/release-please.yml
git commit -m "ci: configure release-please for automated releases"
```

---

## Phase 3: Supply Chain Security

### Task 8: Add Dependabot configuration

**Files:**
- Create: `.github/dependabot.yml`

- [ ] **Step 1: Create Dependabot config**

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
      day: monday
    groups:
      minor-and-patch:
        update-types: [minor, patch]
    labels: ["dependencies", "python"]

  - package-ecosystem: npm
    directory: /typescript
    schedule:
      interval: weekly
      day: monday
    groups:
      minor-and-patch:
        update-types: [minor, patch]
    labels: ["dependencies", "typescript"]

  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
      day: monday
    groups:
      actions:
        patterns: ["*"]
    labels: ["dependencies", "ci"]
```

- [ ] **Step 2: Commit**

```bash
git add .github/dependabot.yml
git commit -m "ci: add Dependabot for automated dependency updates"
```

---

### Task 9: Add CodeQL workflow

**Files:**
- Create: `.github/workflows/codeql.yml`

- [ ] **Step 1: Create CodeQL workflow**

```yaml
name: CodeQL

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: "0 8 * * 1"

permissions:
  security-events: write
  contents: read

jobs:
  analyze:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        language: [python, javascript-typescript]
    steps:
      - uses: actions/checkout@v6
      - uses: github/codeql-action/init@v3
        with:
          languages: ${{ matrix.language }}
          queries: security-extended
      - uses: github/codeql-action/autobuild@v3
      - uses: github/codeql-action/analyze@v3
        with:
          category: "/language:${{ matrix.language }}"
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/codeql.yml
git commit -m "ci: add CodeQL SAST scanning for Python and TypeScript"
```

---

### Task 10: Add SBOM generation to release workflow

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Add SBOM step to Python build job**

In the `build` job of `release.yml`, add after the `uv run twine check dist/*` step:

```yaml
      - name: Generate Python SBOM
        run: |
          uv run pip install cyclonedx-bom
          uv run cyclonedx-py environment --output-format json -o dist/sbom-python.cdx.json
      - uses: actions/upload-artifact@v7
        with:
          name: dist
          path: dist/*
```

Replace the existing `upload-artifact` step (don't duplicate).

- [ ] **Step 2: Add SBOM step to TypeScript build job**

In the `build-typescript` job, add after `npm run build`:

```yaml
      - name: Generate TypeScript SBOM
        run: npx @cyclonedx/cyclonedx-npm --output-format json --output-file dist/sbom-typescript.cdx.json
      - uses: actions/upload-artifact@v7
        with:
          name: typescript-dist
          path: typescript/dist/
```

Replace the existing `upload-artifact` step.

- [ ] **Step 3: Add SBOM upload to GitHub Release**

Add a new job after `publish-npm`:

```yaml
  upload-sboms:
    needs: [build, build-typescript]
    runs-on: ubuntu-latest
    if: github.event_name == 'release'
    permissions:
      contents: write
    steps:
      - uses: actions/download-artifact@v8
        with:
          name: dist
          path: dist
      - uses: actions/download-artifact@v8
        with:
          name: typescript-dist
          path: typescript-dist
      - name: Upload SBOMs to release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release upload "${{ github.event.release.tag_name }}" \
            dist/sbom-python.cdx.json \
            typescript-dist/sbom-typescript.cdx.json \
            --clobber
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add CycloneDX SBOM generation to release pipeline"
```

---

### Task 11: Add artifact signing with Sigstore

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Add signing step to the upload-sboms job**

Rename the job to `sign-and-upload` and add signing before upload:

```yaml
  sign-and-upload:
    needs: [build, build-typescript]
    runs-on: ubuntu-latest
    if: github.event_name == 'release'
    permissions:
      contents: write
      id-token: write
    steps:
      - uses: actions/download-artifact@v8
        with:
          name: dist
          path: dist
      - uses: actions/download-artifact@v8
        with:
          name: typescript-dist
          path: typescript-dist
      - uses: sigstore/gh-action-sigstore-python@v3
        with:
          inputs: dist/*.whl dist/*.tar.gz
      - name: Upload artifacts and signatures to release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release upload "${{ github.event.release.tag_name }}" \
            dist/*.whl dist/*.tar.gz dist/*.sigstore.json \
            dist/sbom-python.cdx.json \
            typescript-dist/sbom-typescript.cdx.json \
            --clobber
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add Sigstore artifact signing to release pipeline"
```

---

## Phase 4: Operational Hardening

### Task 12: Pin GitHub Actions by SHA

**Files:**
- Modify: `.github/workflows/ci-python.yml`
- Modify: `.github/workflows/ci-typescript.yml`
- Modify: `.github/workflows/ci-shared.yml`
- Modify: `.github/workflows/ci-spec.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `.github/workflows/release-please.yml`
- Modify: `.github/workflows/codeql.yml`

- [ ] **Step 1: Replace all action references with SHA pins**

Apply these replacements across ALL workflow files:

| Current | Pinned |
|---------|--------|
| `actions/checkout@v6` | `actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6` |
| `actions/setup-python@v6` | `actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405  # v6` |
| `actions/setup-node@v6` | `actions/setup-node@53b83947a5a98c8d113130e565377fae1a50d02f  # v6` |
| `actions/upload-artifact@v7` | `actions/upload-artifact@bbbca2ddaa5d8feaa63e36b76fdaad77386f024f  # v7` |
| `actions/download-artifact@v8` | `actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c  # v8` |
| `astral-sh/setup-uv@v7` | `astral-sh/setup-uv@94527f2e458b27549849d47d273a16bec83a01e9  # v7` |
| `pypa/gh-action-pypi-publish@release/v1` | `pypa/gh-action-pypi-publish@ed0c53931b1dc9bd32cbe73a98c7f6766f8a527e  # release/v1` |

For CodeQL actions (`github/codeql-action/*@v3`), look up the SHA:
```bash
gh api repos/github/codeql-action/git/ref/tags/v3 --jq '.object.sha'
```

For release-please (`googleapis/release-please-action@v4`):
```bash
gh api repos/googleapis/release-please-action/git/ref/tags/v4 --jq '.object.sha'
```

For sigstore (`sigstore/gh-action-sigstore-python@v3`):
```bash
gh api repos/sigstore/gh-action-sigstore-python/git/ref/tags/v3 --jq '.object.sha'
```

Apply the same pattern: `owner/action@<full-sha>  # <tag>`.

- [ ] **Step 2: Verify all workflow files parse correctly**

```bash
for f in .github/workflows/*.yml; do
  python3 -c "import yaml; yaml.safe_load(open('$f'))" && echo "OK: $f" || echo "FAIL: $f"
done
```

Expected: All OK.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/
git commit -m "ci: pin all GitHub Actions to SHA for supply chain security"
```

---

### Task 13: Add flaky test handling

**Files:**
- Modify: `pyproject.toml` (add pytest-rerunfailures dependency)
- Modify: `tests/performance/test_performance_smoke.py`

- [ ] **Step 1: Add pytest-rerunfailures to dev dependencies**

In `pyproject.toml`, add to the `[dependency-groups] dev` list:

```
  "pytest-rerunfailures>=14.0",
```

- [ ] **Step 2: Restore tight performance threshold and add flaky marker**

In `tests/performance/test_performance_smoke.py`, change:

```python
MAX_EVENT_NAME_NS = 25_000
```

back to:

```python
MAX_EVENT_NAME_NS = 10_000
```

And add `@pytest.mark.flaky(reruns=2)` to the timing-sensitive test class:

```python
@pytest.mark.flaky(reruns=2)
class TestEventNamePerformance:
```

This requires importing or registering the marker. `pytest-rerunfailures` auto-registers it.

- [ ] **Step 3: Sync dependencies**

```bash
uv sync --group dev
```

- [ ] **Step 4: Run performance tests to verify**

```bash
uv run python scripts/run_pytest_gate.py -k "TestEventNamePerformance" --no-cov -q
```

Expected: PASS (with potential reruns shown).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/performance/test_performance_smoke.py
git commit -m "test: add pytest-rerunfailures for flaky performance tests"
```

---

### Task 14: Final verification

- [ ] **Step 1: Run full Python test suite**

```bash
uv run python scripts/run_pytest_gate.py
```

Expected: PASS with 100% coverage.

- [ ] **Step 2: Run full TypeScript test suite**

```bash
cd typescript && npm run test:coverage && cd ..
```

Expected: PASS.

- [ ] **Step 3: Run all linters**

```bash
uv run ruff check .
uv run mypy src tests
uv run ty check src tests
uv run vulture src/ tests/
```

Expected: All clean.

- [ ] **Step 4: Validate all workflow YAML**

```bash
for f in .github/workflows/*.yml; do
  python3 -c "import yaml; yaml.safe_load(open('$f'))" && echo "OK: $f" || echo "FAIL: $f"
done
```

Expected: All OK.

- [ ] **Step 5: List all new/modified files**

```bash
git diff --stat origin/main...HEAD
```

Verify all expected files are present and no unexpected files are included.
