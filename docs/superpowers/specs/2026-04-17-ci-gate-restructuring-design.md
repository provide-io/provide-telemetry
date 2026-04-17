# CI Gate Restructuring — Design Spec

<!-- SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

## Goal

Add the new `--check-contracts` step to CI and reorganize the `ci-spec.yml` gate into
three clearly-separated tiers — **Surface**, **Contract**, and **Integration** — so
feedback arrives at the right speed and cross-language regressions are caught automatically.

## Background

The recent contract-probe DSL work produced `spec/contract_fixtures.yaml` and four
per-language probe scripts that exercise real public APIs across all four languages.
The harness is invoked via:

```bash
python spec/run_behavioral_parity.py --check-contracts
```

This flag exists, the harness works, but it is **not yet wired into any CI job**.
Without CI coverage the new contract tests provide no protection.

Additionally, the three existing checks in `ci-spec.yml` — API conformance, version sync,
and behavioral parity — are conceptually different in speed, dependencies, and what they
catch. Mixing them in one workflow makes failures harder to attribute and wastes matrix
capacity when only one check changes.

## Current State

```
ci-spec.yml
  ├─ conformance       (ubuntu only, ~30s) — validate_conformance.py
  ├─ version-sync      (ubuntu only, ~15s) — check_version_sync.py
  └─ behavioral-parity (ubuntu, all 4 runtimes, ~3–5 min) — run_behavioral_parity.py --check-output
```

Missing: `--check-contracts` step in behavioral-parity (needs all 4 runtimes, ~2–4 min).

Missing path triggers: `spec/contract_fixtures.yaml`, `spec/probes/contract_probe_*`,
`spec/contract_probe_harness.py` are not in the `paths:` filter, so contract file
changes don't trigger the spec workflow.

## Proposed Structure

Split `ci-spec.yml` into two files:

### `ci-surface.yml` — fast, zero runtime dependencies

Jobs: `conformance`, `version-sync`.
Runs on every push/PR to main. ~30–60s total.
Needs only Python (uv); no Go, Node, Rust.
Path triggers: `spec/telemetry-api.yaml`, `spec/validate_conformance.py`,
`scripts/check_version_sync.py`, `VERSION`, language `**/__init__.py` exports,
`go/telemetry.go`, `typescript/src/index.ts`, `rust/src/lib.rs`.

### `ci-contracts.yml` — cross-language behavioral contracts

Jobs: `output-parity`, `contract-probes` (new).
Runs on push/PR to main when contract-relevant files change.
Needs all 4 runtimes. ~5–10 min total.
Path triggers: `spec/**`, `src/provide/telemetry/**`, `typescript/src/**`,
`go/**`, `rust/src/**`, `rust/examples/contract_probe.rs`.

The two jobs within `ci-contracts.yml` can run in parallel (both need all 4 runtimes,
so the setup cost is the same):

```
ci-contracts.yml
  ├─ output-parity    — run_behavioral_parity.py --check-output
  └─ contract-probes  — run_behavioral_parity.py --check-contracts
```

## Detailed Changes

### File: `.github/workflows/ci-surface.yml` (new)

Copy `conformance` and `version-sync` jobs verbatim from `ci-spec.yml`.
Add expanded path triggers covering all language API export files.

```yaml
name: 📐 CI — Surface Conformance
on:
  push:
    branches: [main]
    paths:
      - "spec/telemetry-api.yaml"
      - "spec/validate_conformance.py"
      - "scripts/check_version_sync.py"
      - "VERSION"
      - "src/provide/telemetry/__init__.py"
      - "typescript/src/index.ts"
      - "go/telemetry.go"
      - "rust/src/lib.rs"
      - ".github/workflows/ci-surface.yml"
  pull_request:
    branches: [main]
    paths: [same as above]
  workflow_dispatch:
```

Jobs: `conformance` and `version-sync` (unchanged from current `ci-spec.yml`).

### File: `.github/workflows/ci-contracts.yml` (new)

Two parallel jobs sharing the same runtime setup pattern as today's `behavioral-parity`.

```yaml
name: 📐 CI — Contract Parity
on:
  push:
    branches: [main]
    paths:
      - "spec/**"
      - "ci/**"
      - "src/provide/telemetry/**"
      - "typescript/src/**"
      - "go/**"
      - "rust/src/**"
      - "rust/examples/contract_probe.rs"
      - "VERSION"
      - ".github/workflows/ci-contracts.yml"
  pull_request:
    branches: [main]
    paths: [same as above]
  workflow_dispatch:
```

#### Job: `output-parity`

Identical to today's `behavioral-parity` job. Runs all 4 language parity suites and
cross-compares canonical JSON fields via `--check-output`.

```yaml
- name: Behavioral parity check (output format)
  run: python spec/run_behavioral_parity.py --check-output
```

#### Job: `contract-probes` (new)

Same runtime setup (uv, node, go, rust, cargo cache). Runs the contract DSL:

```yaml
- name: Contract probe check (cross-language semantics)
  run: python spec/run_behavioral_parity.py --check-contracts
```

Runtime setup is identical between both jobs (reuse the same steps block).
They can be extracted to a composite action `ci/setup-parity-runtimes/action.yml`
to avoid drift, but that is optional scope (see "Out of scope" below).

### File: `.github/workflows/ci-spec.yml` (delete)

Remove after `ci-surface.yml` and `ci-contracts.yml` are confirmed green on main.

### File: `spec/run_behavioral_parity.py` (no change needed)

`--check-contracts` flag and timeout forwarding already implemented.

### File: `rust/Cargo.toml` (already has `serde_yaml`)

No change needed.

## Out of Scope

- Composite action for shared runtime setup (nice-to-have; deduplicate later).
- `--check-contracts` timeout tuning (default 300s per language is sufficient).
- Adding `--check-contracts` to the nightly schedule (default `workflow_dispatch` is enough for now; add cron after first green CI cycle).
- Splitting per-language CI workflows (Python, TypeScript, Go, Rust) — out of scope; they are already well-structured.
- `ci-mutation.yml` reorganization — out of scope.

## Migration Path

1. Create `ci-surface.yml` with conformance + version-sync jobs.
2. Create `ci-contracts.yml` with output-parity + contract-probes jobs.
3. Verify both fire and pass on a test branch.
4. Delete `ci-spec.yml` in a follow-up commit (after one green CI cycle on main).

## File Checklist

**Create:**
- `.github/workflows/ci-surface.yml`
- `.github/workflows/ci-contracts.yml`

**Delete (after green cycle):**
- `.github/workflows/ci-spec.yml`

**No changes:**
- All other workflow files
- `spec/run_behavioral_parity.py`
- All probe scripts

## Success Criteria

1. `ci-surface.yml` runs in < 90s on any push to main.
2. `ci-contracts.yml` runs `--check-output` and `--check-contracts` in parallel; both green.
3. A change to `spec/contract_fixtures.yaml` triggers `ci-contracts.yml` but not `ci-surface.yml`.
4. `ci-spec.yml` is deleted.
5. All SPDX headers present.
