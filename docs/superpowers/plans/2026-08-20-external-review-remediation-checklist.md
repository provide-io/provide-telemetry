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

- [x] Regression test proves late host replacement survives `ShutdownTelemetry`
      (traces, metrics, logs).
- [x] Regression test proves the conflict warning fires for a host-installed
      concrete SDK provider.
- [x] Negative control: revert the identity check, confirm the test fails, restore.
- [x] `go test ./... -race` green in `go/` and `go/otel/`.
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
- [x] `h2` upgraded to the patched version. If unreachable under current
      constraints → **stop and escalate**, record the blocking constraint here.
- [x] Rust gate: `cargo-audit` + `rust/deny.toml` advisory-expiry checker, blocking.
- [x] Python gate: audits packages exported from committed `uv.lock`, blocking.
- [x] TypeScript: outstanding dev findings upgraded away, **then** gate blocking.
- [x] C# gate: `dotnet list package --vulnerable --include-transitive` across the
      whole solution, blocking.
- [x] Go: confirmed `gosec` + `govulncheck` already present; no new gate.
- [x] Each gate has a test proving a zero-package inventory **fails**.
- [x] Each gate has a test proving a simulated finding **fails**.

**Outcome:** upgraded h2 0.4.15 -> 0.4.18 (`cargo update -p h2 --precise 0.4.18`).
`cargo audit` now scans 248 crates clean. The same command also re-points five
Windows-only crates from `windows-sys 0.61.2` to `0.52.0`; those crates declare
`^0.52`, which `0.61.2` never satisfied, and cargo 1.97.1 corrects it on any
re-resolve — it is not reachable-by-`h2` and not avoidable with `--precise`.
Rust suite green after the bump (517 lib tests, zero failures across all suites).

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

### 3. Rust line-coverage gate — **UNRESOLVED, needs a decision**

**Plan:** [`2026-08-20-security-and-coverage-gates.md`](2026-08-20-security-and-coverage-gates.md) — Task 9

`.github/workflows/ci-rust.yml:102` passes `--fail-uncovered-lines 0`.

- [x] Controlled coverage fixture with a known-uncovered line built.
- [x] Current command run against the fixture; result recorded below.
- [x] Current command run against the **real repository**; result recorded below.
- [ ] **Not resolved.** The three measurements disagree, so no flag change was
      made. Flipping the flag would fail `ci-rust.yml` on coverage debt that
      cannot currently be located reliably, which is worse than the status quo.
- [ ] `CLAUDE.md` coverage command — unchanged, in lockstep with the workflow.

**Evidence — three measurements, two of which disagree:**

*1. Synthetic fixture (100% functions, 87.5% lines) — the flag FIRES:*

```
# else arm untested
TOTAL  functions 2 missed 0 = 100.00%   lines 8 missed 1 = 87.50%
--fail-uncovered-lines 0 --fail-under-functions 100   ->  exit 1
# both arms tested
TOTAL  functions 2 missed 0 = 100.00%   lines 7 missed 0 = 100.00%
--fail-uncovered-lines 0 --fail-under-functions 100   ->  exit 0
```

*2. Real repository (100% functions, 99.77% lines) — the flag does NOT fire:*

```
TOTAL   10465 regions, 32 missed, 99.69% | 854 functions, 0 missed, 100.00%
        6905 lines,   16 missed, 99.77%
otel/bounded.rs        202 lines, 14 missed, 93.07%
runtime_facade.rs      264 lines,  2 missed, 99.24%

--fail-uncovered-lines 0 --fail-under-functions 100   ->  exit 0   <-- 16 uncovered lines pass
--fail-under-lines 100  --fail-under-functions 100    ->  exit 1
```

*3. lcov export of the same run — reports ZERO uncovered lines:*

```
$ cargo llvm-cov ... --lcov --output-path cov.lcov
$ grep -c '^DA:' cov.lcov        -> 6746
$ grep -c '^DA:.*,0$' cov.lcov   -> 0
```

**Reading.** On the artifact that matters — this repository — the current flag
lets 16 uncovered source lines through and the proposed replacement rejects
them, so the review's concern is very likely correct and my earlier
"false positive" reading was premature. But measurement 3 contradicts
measurement 2 about whether those lines are uncovered at all, and the coverage
run is itself intermittently broken by the recommendation-10 flake, so the
input is not trustworthy enough to justify a change that turns CI red.

**Decision needed:**

1. Flip to `--fail-under-lines 100` and cover `otel/bounded.rs` (14 lines) and
   `runtime_facade.rs` (2 lines) — note that `otel/bounded.rs` is the
   abandoned-worker machinery implicated in recommendation 10, so this is
   entangled with that investigation; or
2. Flip the flag and accept a red `ci-rust.yml` until the debt is paid; or
3. Leave the flag and track the debt separately.

### 4. `event_name` standardization — **BREAKING for Go and C#**

**Plan:** [`2026-08-20-runtime-contract-remediation.md`](2026-08-20-runtime-contract-remediation.md) — Tasks 4–10

Contract: relaxed = 1+ non-empty segments, no grammar check. Strict = 3–5
segments, each matching `^[a-z][a-z0-9_]*$`. Zero segments always fail. Empty
segment always fails, both modes. `Event()` / `event()` is **out of scope** and
keeps its 3-or-4 rule.

- [x] `spec/telemetry-api.yaml` `event_schema` block restructured for both modes
      and both entry points.
- [x] `spec/behavioral_fixtures.yaml` gains an `event_name_contract` category.
- [x] `spec/fixture_test_ids.yaml` maps every new case ID per language.
- [x] Go `EventName` / `ValidateEventName` honour relaxed mode.
- [x] C# `EventName` / `ValidateEventName` honour relaxed mode.
- [x] C# `ValidateEventName` reads `GetStrictSchema()` (second, independent defect).
- [ ] Python / TypeScript / Rust confirmed unchanged, with tests proving it.
- [x] `Event()` behavior proven unchanged in all five languages.
- [x] `spec/run_behavioral_parity.py` green across all five languages.
- [x] `spec/check_fixture_coverage.py` and `check_fixture_test_ids.py` green.
- [x] `spec/validate_conformance.py` green — spec and implementations agree.
- [x] `CHANGELOG.md` carries a BREAKING entry naming Go and C#, old behavior,
      new behavior, and the migration.
- [x] `go/README.md` and `csharp/README.md` state the relaxed-mode rule.
- [ ] Mutation gates green: gremlins (Go root + `schemacore`), Stryker (C#).

**Evidence:**
```
(paste parity + conformance + mutation results)
```

### 5. Documentation accuracy

**Plan:** [`2026-08-20-documentation-accuracy.md`](2026-08-20-documentation-accuracy.md)

- [x] `go/README.md:13` and `:268` — "Go 1.22+" corrected to match
      `go/go.mod:3` (`go 1.26.0`).
- [x] `rust/README.md:16` — `"0.3"` corrected to the shipped version.
- [ ] `rust/README.md:24-36` — lifecycle snippet corrected to the real
      signatures (`setup_telemetry(Option<TelemetryConfig>)`,
      `shutdown_telemetry(Option<f64>)`, both returning `Result`).
- [x] `docs/guide/capability-matrix.md:61-65` — C# OTLP evidence claim corrected
      to cite `WireDeliveryTests` / `FakeOtlpCollector`.
- [ ] Stale "four languages" comments fixed: `ci-spec.yml:49`,
      `ci-contracts.yml:73`, `:80`, `:116`, `ci-surface.yml:64`, `:68`.
- [x] `scripts/check_docs_accuracy.py:15` mutation-score language reconciled
      with the enforced 100 percent kill.
- [ ] `scripts/check_docs_accuracy.py:11` `DOC_PATHS` widened to include
      `go/README.md`, `rust/README.md`, `typescript/README.md`,
      `csharp/README.md`, `CONTRIBUTING.md`.
- [x] Executable snippet test compiles/runs the Rust quick start.
- [x] Executable snippet test compiles/runs the Go quick start.
- [x] `uv run python scripts/check_docs_accuracy.py` green.

**Evidence:**
```
(paste checker output)
```

### 6. npm publication failures no longer masked

**Plan:** [`2026-08-20-npm-release-and-typescript-context.md`](2026-08-20-npm-release-and-typescript-context.md) — Tasks 1–2

- [x] `continue-on-error: true` removed from `publish-npm`
      (`.github/workflows/release.yml:255`). **Everything else is inert until
      this line is gone.**
- [x] Pre-publish registry query for the exact version.
- [x] Existing version → documented successful no-op.
- [x] Auth / network / package / provenance / new-version failures → fatal.
- [x] Postcondition verifies the requested version exists after the job.
- [x] Publish logic lives in a `ci/` script, not inline YAML (repo policy).
- [x] Script unit-tested for: version-exists, version-absent, registry error.

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

- [x] README install instructions name `@opentelemetry/context-async-hooks` and
      say what breaks without it in Node.
- [x] Non-Node runtime → silent, no `setupError`.
- [x] Node + module not found → actionable `setupError` + one-time warning.
- [x] Node + context manager construction/enable throws → actionable
      `setupError` + one-time warning.
- [x] Message visible from `getHealthSnapshot().setupError` **and**
      `getRuntimeStatus().setupError`.
- [x] Later success clears only its own message, never an unrelated setup error.
- [x] Fail-open confirmed: signal export still works with the context manager
      absent.
- [x] No new public status fields added.
- [ ] Stryker green for both TypeScript configs.

**Evidence:**
```
(paste vitest + stryker results)
```

### 8. C# NuGet package artifact verification

**Plan:** [`2026-08-20-csharp-package-verification.md`](2026-08-20-csharp-package-verification.md)

- [x] `docs/guide/capability-matrix.md` corrected to cite the existing
      credential-free `WireDeliveryTests` / `FakeOtlpCollector`.
- [x] CI packs both packages into a temporary local feed.
- [x] Consumer projects use `PackageReference` only — **no `ProjectReference`**.
- [x] Exact-version installs from the temporary feed (no nuget.org fallback).
- [x] OTel consumer proves registration activates the backend.
- [x] Core-only consumer proves the BCL-only boundary holds (no OTel assembly
      resolvable).
- [x] Both consumers build **and run**, not just restore.
- [x] Credentialed OpenObserve tests retained, not replaced.

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

- [x] Failing test identified by name and file; original output preserved.
- [x] Statistical reproduction: N runs, failure count recorded.
- [ ] Deterministic fault-injected reproducer built.
- [ ] Lifecycle / generation instrumentation demonstrates the root cause.
- [ ] Regression test fails without the fix.
- [ ] Negative control: fix temporarily reverted, test observed failing, restored.
- [ ] Regression test passes with the fix.
- [ ] Parallel stress run green.
- [ ] Serial stress run green.
- [x] **OR** recorded as inconclusive with commands, observations, and rejected
      hypotheses — and no production change made. See
      [`evidence/2026-08-20-rust-flake-inconclusive.md`](evidence/2026-08-20-rust-flake-inconclusive.md).

**Evidence:** reproduced at 4/14 full-suite runs, and again under
`RUST_TEST_THREADS=1` — which rules out concurrent test bodies entirely. Two
signatures; the informative one is a *successful* export (latency 1.17ms, zero
failures) that the asserting collector never saw. The obvious hypothesis (tests
racing without the shared state lock) was tested and REJECTED: those tests take
the lock through a helper returning the guard, and a second acquisition
deadlocked the suite. A second, more tractable flaky test in the same
abandoned-worker machinery was found and documented. No production change, no
quarantine.

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
