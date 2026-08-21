# External Review Remediation — Umbrella Checklist

**Spec:** [`docs/superpowers/specs/2026-08-20-external-review-remediation-design.md`](../specs/2026-08-20-external-review-remediation-design.md) (revision 2)

This is the single tracking document for the 2026-08-20 five-language external
review. A recommendation is checked **only** when the evidence column holds a
command that was actually run and its observed result — not a plan to run it.

## Execution order and dependencies

```
Baseline (above)   ──┬─→ Plan 2 (security + coverage gates)   [rec 2, 3]
                     ├─→ Plan 1 (runtime contracts)           [rec 1, 4]
                     ├─→ Plan 3 (npm + TS context)            [rec 6, 7]
                     ├─→ Plan 5 (C# package evidence)         [rec 8]
                     └─→ Plan 6 (Rust flake, isolated)        [rec 10]
                                    ↓ all of the above
                            Plan 4 (documentation)            [rec 5]
```

Plan 4 runs **last**: it documents behavior the other plans change. Plan 6 runs
in its own branch or worktree so no dependency or coverage change can be
mistaken for the flake fix.

## Baseline (do this first — no separate plan file)

- [x] Working tree clean at start: `git status --short` prints nothing.
- [x] Baseline commit SHA recorded here: `0a48973f`
- [ ] Original Rust failure evidence preserved verbatim at
      `docs/superpowers/plans/evidence/2026-08-20-rust-flake-original.txt`.
      If the original output was not captured anywhere, record that fact
      explicitly — do not reconstruct it.

## Recommendations

### 1. Go OpenTelemetry global-provider ownership

**Plan:** [`2026-08-20-runtime-contract-remediation.md`](2026-08-20-runtime-contract-remediation.md) — Tasks 1–3

Defect: `_resetGlobalsWeSet()` (`go/otel/backend.go:217-231`) resets the global
to a no-op whenever its ownership boolean is set, without checking the global
still holds the provider Provide installed. A host that calls
`otel.SetTracerProvider` after setup loses its provider at shutdown.
Second defect: `_warnIfTracerProviderConflict` (`go/otel/providers.go:19-36`)
suppresses the warning for any `*sdktrace.TracerProvider`, treating a host SDK
provider as Provide-owned.

- [ ] Regression test proves late host replacement survives `ShutdownTelemetry`
      (traces, metrics, logs).
- [ ] Regression test proves the conflict warning fires for a host-installed
      concrete SDK provider.
- [ ] Negative control: revert the identity check, confirm the test fails, restore.
- [ ] `go test ./... -race` green in `go/` and `go/otel/`.
- [ ] Gremlins gate green for the `otel` module.

**Evidence:**
```
(paste commands + results)
```

### 2. Rust `h2` upgrade + dependency vulnerability gates

**Plan:** [`2026-08-20-security-and-coverage-gates.md`](2026-08-20-security-and-coverage-gates.md) — Tasks 1–8

`rust/Cargo.lock:514-516` pins `h2 0.4.15`. The advisory ID is **not** recorded
in the review; step one is to obtain it from `cargo audit`, not to assume it.

- [x] `cargo audit` run against committed `rust/Cargo.lock`; advisory ID,
      affected range, and patched version recorded below.
- [ ] `h2` upgraded to the patched version. If unreachable under current
      constraints → **stop and escalate**, record the blocking constraint here.
- [ ] Rust gate: `cargo-audit` + `rust/deny.toml` advisory-expiry checker, blocking.
- [ ] Python gate: audits packages exported from committed `uv.lock`, blocking.
- [ ] TypeScript: outstanding dev findings upgraded away, **then** gate blocking.
- [ ] C# gate: `dotnet list package --vulnerable --include-transitive` across the
      whole solution, blocking.
- [ ] Go: confirmed `gosec` + `govulncheck` already present; no new gate.
- [ ] Each gate has a test proving a zero-package inventory **fails**.
- [ ] Each gate has a test proving a simulated finding **fails**.

**Advisory evidence:**
```
$ cd rust && cargo audit
    Loaded 1225 security advisories (from /Users/tim/.cargo/advisory-db)
    Scanning Cargo.lock for vulnerabilities (248 crate dependencies)
Crate:     h2
Version:   0.4.15
Title:     h2 unbounded empty DATA frames
Date:      2026-08-17
ID:        RUSTSEC-2026-0258
URL:       https://rustsec.org/advisories/RUSTSEC-2026-0258
Solution:  Upgrade to >=0.4.16
Dependency tree: h2 0.4.15 <- hyper 1.11.0 <- {tonic 0.14.6, reqwest 0.12.28,
  hyper-util 0.1.20, hyper-timeout 0.5.2, hyper-rustls 0.27.9}
  ... <- opentelemetry-otlp 0.31.1 <- provide-telemetry 0.8.0

error: 1 vulnerability found!

advisory id:      RUSTSEC-2026-0258
affected range:   h2 < 0.4.16
patched version:  0.4.16
command:          cd rust && cargo audit   (cargo-audit 0.22.1)
```

### 3. Rust line-coverage gate

**Plan:** [`2026-08-20-security-and-coverage-gates.md`](2026-08-20-security-and-coverage-gates.md) — Task 9

`.github/workflows/ci-rust.yml:102` passes `--fail-uncovered-lines 0`. The claim
that this is inert is **unverified**. Prove it before changing it.

- [ ] Controlled coverage fixture with a known-uncovered line built.
- [ ] Current command run against the fixture; result recorded below.
- [ ] If the current command **fails** correctly → close as false positive with
      that evidence, make no flag change, and note it here.
- [ ] If the current command **passes** → replace with `--fail-under-lines 100`
      and prove the fixture now fails.
- [ ] `CLAUDE.md` coverage command updated in lockstep with the workflow.

**Evidence:**
```
(paste the fixture run under the OLD flag, then under the NEW flag)
```

### 4. `event_name` standardization — **BREAKING for Go and C#**

**Plan:** [`2026-08-20-runtime-contract-remediation.md`](2026-08-20-runtime-contract-remediation.md) — Tasks 4–10

Contract: relaxed = 1+ non-empty segments, no grammar check. Strict = 3–5
segments, each matching `^[a-z][a-z0-9_]*$`. Zero segments always fail. Empty
segment always fails, both modes. `Event()` / `event()` is **out of scope** and
keeps its 3-or-4 rule.

- [ ] `spec/telemetry-api.yaml` `event_schema` block restructured for both modes
      and both entry points.
- [ ] `spec/behavioral_fixtures.yaml` gains an `event_name_contract` category.
- [ ] `spec/fixture_test_ids.yaml` maps every new case ID per language.
- [ ] Go `EventName` / `ValidateEventName` honour relaxed mode.
- [ ] C# `EventName` / `ValidateEventName` honour relaxed mode.
- [ ] C# `ValidateEventName` reads `GetStrictSchema()` (second, independent defect).
- [ ] Python / TypeScript / Rust confirmed unchanged, with tests proving it.
- [ ] `Event()` behavior proven unchanged in all five languages.
- [ ] `spec/run_behavioral_parity.py` green across all five languages.
- [ ] `spec/check_fixture_coverage.py` and `check_fixture_test_ids.py` green.
- [ ] `spec/validate_conformance.py` green — spec and implementations agree.
- [ ] `CHANGELOG.md` carries a BREAKING entry naming Go and C#, old behavior,
      new behavior, and the migration.
- [ ] `go/README.md` and `csharp/README.md` state the relaxed-mode rule.
- [ ] Mutation gates green: gremlins (Go root + `schemacore`), Stryker (C#).

**Evidence:**
```
(paste parity + conformance + mutation results)
```

### 5. Documentation accuracy

**Plan:** [`2026-08-20-documentation-accuracy.md`](2026-08-20-documentation-accuracy.md)

- [ ] `go/README.md:13` and `:268` — "Go 1.22+" corrected to match
      `go/go.mod:3` (`go 1.26.0`).
- [ ] `rust/README.md:16` — `"0.3"` corrected to the shipped version.
- [ ] `rust/README.md:24-36` — lifecycle snippet corrected to the real
      signatures (`setup_telemetry(Option<TelemetryConfig>)`,
      `shutdown_telemetry(Option<f64>)`, both returning `Result`).
- [ ] `docs/guide/capability-matrix.md:61-65` — C# OTLP evidence claim corrected
      to cite `WireDeliveryTests` / `FakeOtlpCollector`.
- [ ] Stale "four languages" comments fixed: `ci-spec.yml:49`,
      `ci-contracts.yml:73`, `:80`, `:116`, `ci-surface.yml:64`, `:68`.
- [ ] `scripts/check_docs_accuracy.py:15` mutation-score language reconciled
      with the enforced 100 percent kill.
- [ ] `scripts/check_docs_accuracy.py:11` `DOC_PATHS` widened to include
      `go/README.md`, `rust/README.md`, `typescript/README.md`,
      `csharp/README.md`, `CONTRIBUTING.md`.
- [ ] Executable snippet test compiles/runs the Rust quick start.
- [ ] Executable snippet test compiles/runs the Go quick start.
- [ ] `uv run python scripts/check_docs_accuracy.py` green.

**Evidence:**
```
(paste checker output)
```

### 6. npm publication failures no longer masked

**Plan:** [`2026-08-20-npm-release-and-typescript-context.md`](2026-08-20-npm-release-and-typescript-context.md) — Tasks 1–2

- [ ] `continue-on-error: true` removed from `publish-npm`
      (`.github/workflows/release.yml:255`). **Everything else is inert until
      this line is gone.**
- [ ] Pre-publish registry query for the exact version.
- [ ] Existing version → documented successful no-op.
- [ ] Auth / network / package / provenance / new-version failures → fatal.
- [ ] Postcondition verifies the requested version exists after the job.
- [ ] Publish logic lives in a `ci/` script, not inline YAML (repo policy).
- [ ] Script unit-tested for: version-exists, version-absent, registry error.

**Evidence:**
```
(paste script test results + workflow lint)
```

### 7. TypeScript async-context observability

**Plan:** [`2026-08-20-npm-release-and-typescript-context.md`](2026-08-20-npm-release-and-typescript-context.md) — Tasks 3–5

Correction to the review: `@opentelemetry/context-async-hooks` is **already** a
declared `peerDependency` in `typescript/package.json`. The gaps are that it is
undocumented in install instructions and that `typescript/src/otel.ts:106-108`
swallows every failure in a bare `catch {}`.

- [ ] README install instructions name `@opentelemetry/context-async-hooks` and
      say what breaks without it in Node.
- [ ] Non-Node runtime → silent, no `setupError`.
- [ ] Node + module not found → actionable `setupError` + one-time warning.
- [ ] Node + context manager construction/enable throws → actionable
      `setupError` + one-time warning.
- [ ] Message visible from `getHealthSnapshot().setupError` **and**
      `getRuntimeStatus().setupError`.
- [ ] Later success clears only its own message, never an unrelated setup error.
- [ ] Fail-open confirmed: signal export still works with the context manager
      absent.
- [ ] No new public status fields added.
- [ ] Stryker green for both TypeScript configs.

**Evidence:**
```
(paste vitest + stryker results)
```

### 8. C# NuGet package artifact verification

**Plan:** [`2026-08-20-csharp-package-verification.md`](2026-08-20-csharp-package-verification.md)

- [ ] `docs/guide/capability-matrix.md` corrected to cite the existing
      credential-free `WireDeliveryTests` / `FakeOtlpCollector`.
- [ ] CI packs both packages into a temporary local feed.
- [ ] Consumer projects use `PackageReference` only — **no `ProjectReference`**.
- [ ] Exact-version installs from the temporary feed (no nuget.org fallback).
- [ ] OTel consumer proves registration activates the backend.
- [ ] Core-only consumer proves the BCL-only boundary holds (no OTel assembly
      resolvable).
- [ ] Both consumers build **and run**, not just restore.
- [ ] Credentialed OpenObserve tests retained, not replaced.

**Evidence:**
```
(paste pack + restore + run output)
```

### 9. Automated dependency-update pull requests — `DEFERRED BY USER`

- [ ] ~~Enable Dependabot or equivalent~~ — **DEFERRED BY USER.**

No `.github/dependabot.yml` is added, modified, or removed by this remediation.
This item is not a completion blocker. Revisit separately.

### 10. Rust OTLP export-test flake

**Plan:** [`2026-08-20-rust-export-flake-investigation.md`](2026-08-20-rust-export-flake-investigation.md)

Policy: root cause or nothing. No quarantine, no `#[ignore]`, no retry wrapper,
no longer sleeps.

- [ ] Failing test identified by name and file; original output preserved.
- [ ] Statistical reproduction: N runs, failure count recorded.
- [ ] Deterministic fault-injected reproducer built.
- [ ] Lifecycle / generation instrumentation demonstrates the root cause.
- [ ] Regression test fails without the fix.
- [ ] Negative control: fix temporarily reverted, test observed failing, restored.
- [ ] Regression test passes with the fix.
- [ ] Parallel stress run green.
- [ ] Serial stress run green.
- [ ] **OR** recorded as inconclusive with commands, observations, and rejected
      hypotheses — and no production change made.

**Evidence:**
```
(paste reproduction stats + instrumentation + stress runs)
```

## Final verification matrix

Run after all plans land. Every row needs an observed result.

| Gate | Command | Result |
|---|---|---|
| Python suite | `uv run python scripts/run_pytest_gate.py` | |
| Python lint | `uv run ruff check . && uv run ruff format --check .` | |
| Python types | `uv run mypy src tests` | |
| Python mutation | `uv run python scripts/run_mutation_gate.py --max-children 2 --min-mutation-score 95` | |
| Go tests | `cd go && go test ./... -race` | |
| Go otel tests | `cd go/otel && go test ./... -race` | |
| Go mutation | `scripts/run_gremlins_gate.sh` (all six surfaces) | |
| Rust tests | `cd rust && cargo test --all-features` | |
| Rust coverage | `cargo llvm-cov …` (per `CLAUDE.md`, post-rec-3) | |
| Rust mutation | `cargo mutants --in-place --all-features --shard 1/8` | |
| TypeScript | `cd typescript && npm test` | |
| TypeScript mutation | `npx stryker run --concurrency 2` ×2 configs | |
| C# tests | `cd csharp && dotnet test` | |
| C# mutation | `dotnet stryker` | |
| Max LOC | `uv run python scripts/check_max_loc.py --max-lines 777` | |
| SPDX | `uv run python scripts/check_spdx_headers.py` | |
| Version sync | `uv run python scripts/check_version_sync.py` | |
| Conformance | `uv run python spec/validate_conformance.py` | |
| Behavioral parity | `uv run python spec/run_behavioral_parity.py` | |
| Fixture coverage | `uv run python spec/check_fixture_coverage.py` | |
| Fixture IDs | `uv run python spec/check_fixture_test_ids.py` | |
| Docs accuracy | `uv run python scripts/check_docs_accuracy.py` | |
| Worktree clean | `git status --short` (must be empty) | |

## Completion

Complete when recommendations 1–8 and 10 are checked with real evidence, every
row above has an observed pass, `CHANGELOG.md` records the breaking
`event_name` change, and the tracked worktree is clean. Recommendation 9 stays
unchecked as `DEFERRED BY USER` and does not block completion.
