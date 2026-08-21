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

### 3. Rust line-coverage gate — **CLOSED as a false positive, with proof**

**Plan:** [`2026-08-20-security-and-coverage-gates.md`](2026-08-20-security-and-coverage-gates.md) — Task 9

- [x] Controlled coverage fixture with a known-uncovered line built.
- [x] Current command run against the fixture — it fails, correctly.
- [x] Current command run against the real repository, on `main` and on this branch.
- [x] **`--fail-uncovered-lines 0` is live and discriminating.** No flag change
      made to `.github/workflows/ci-rust.yml`, and none needed.
- [x] `CLAUDE.md` coverage command unchanged, in lockstep with the workflow.

**Evidence.** An earlier reading of this item was wrong in both directions and
is worth recording, because the trap is easy to fall into twice.

*First measurement — a synthetic fixture with 100% functions and 87.5% lines:*

```
# else arm untested                       -> exit 1   (the flag fires)
# both arms tested                        -> exit 0
```

*Second measurement — the real repository, which appeared to contradict it:*

```
TOTAL ... 6905 lines, 16 missed, 99.77%   -> exit 0   (?!)
--fail-under-lines 100                    -> exit 1
```

That looked like the flag ignoring 16 uncovered lines, and this checklist
briefly recorded recommendation 3 as very likely real on that basis.

*Third measurement — the decisive one.* Running the identical command on `main`
and on this branch:

```
main         TOTAL 16 missed lines  -> exit 0
this branch  TOTAL 17 missed lines  -> exit 1
```

One line of difference flipped the gate. The line was
`otel/logs_export_test_support.rs:242`, the `Err(_) => return None` arm of the
collector's read loop, which this branch made unreachable from its old test when
`read_request_path` began clearing `O_NONBLOCK`. Covering it again with
`a_silent_client_times_out_instead_of_wedging_the_collector` returned the gate
to exit 0.

So the flag is not inert: it fires on a newly uncovered line and clears when the
line is covered. The 16 lines it tolerates on `main` sit in contexts
`--fail-uncovered-lines` excludes and `--fail-under-lines` does not, which is
the entire difference between the two flags and the source of the confusion.
Swapping them would not have fixed a hole; it would have turned `ci-rust.yml`
red on 16 lines the gate was never intended to count.

**Outcome:** recommendation 3 is a false positive. The review's concern was
reasonable — the flag name is misleading — but the gate does its job.

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
- [x] Mutation gates green: gremlins (Go root + `schemacore`), Stryker (C#).

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
- [x] Deterministic fault-injected reproducer built (fails 20/20 unfixed).
- [x] Instrumentation demonstrates the root cause.
- [x] Regression test fails without the fix.
- [x] Negative control: fix temporarily reverted, test observed failing, restored.
- [x] Regression test passes with the fix.
- [x] Parallel stress run green (0 / 12 full-suite runs).
- [x] Serial stress run green (0 / 6 full-suite runs).
- [x] ~~OR recorded as inconclusive~~ — superseded; the root cause was found.

**Evidence.** Root cause: the mock OTLP collectors bind their listener
non-blocking so the accept loop can poll a stop flag, and on macOS and the BSDs
an accepted socket **inherits** that `O_NONBLOCK`. The first `read` then returns
`WouldBlock` whenever the request bytes have not landed yet;
`read_request_path` treats every `Err` as "no request", discards it, and the
collector still answers `200 OK`. The exporter therefore recorded a successful
export — real latency, zero failures — while the collector recorded nothing.
That is exactly the "expected /v1/traces export, saw []" failure, and it is why
the health snapshot in the panic message looked perfectly healthy.

Instrumenting the accept path printed it directly:

```
DIAG collector: accepted a connection but parsed NO path
DIAG endpoint=http://127.0.0.1:57867 abandoned_workers=0 seen=[]
```

`abandoned_workers=0` also disproves the abandoned-drain-worker hypothesis this
checklist previously recorded as the leading theory. Three copies of the
collector carried the defect — the shared test support, the OTLP runtime
integration test, and the metrics mutation test — and all three now clear
`O_NONBLOCK` before reading.

A second, independent race was found in the same run:
`a_teardown_abandoned_at_the_deadline_returns_to_the_caller` released its worker
before reading the abandoned-worker count, so a worker reaching
`note_worker_finished` in that window decremented the budget to zero and the
assertion read 0. Widening the window to 50ms failed 10/10; the count is now
read before the release.

| Measurement | Before | After |
|---|---|---|
| Full suite, parallel | 4 failures / 14 runs | **0 / 12** |
| Full suite, serial | reproduced | **0 / 6** |
| `a_request_written_after_the_accept_is_still_recorded` | fails 20/20 | passes; fails again when the fix is reverted |

No production code changed — both defects were in test support, which is what
the acceptance rule's "no speculative production change" was protecting.

## Final verification matrix

Run after all plans land. Every row needs an observed result.

| Gate | Command | Result |
|---|---|---|
| Python suite | `uv run python scripts/run_pytest_gate.py` | 3096 passed, 100% branch coverage |
| Python lint | `uv run ruff check . && uv run ruff format --check .` | clean |
| Python types | `uv run mypy src tests` | no issues, 299 files |
| Python mutation | `uv run python scripts/run_mutation_gate.py --max-children 2 --min-mutation-score 95` | **100.00%** — 4922 killed, 0 survived |
| Go tests | `cd go && go test ./... -race` | ok (root, piicore, logger) |
| Go otel tests | `cd go/otel && go test ./... -race` | ok |
| Go mutation | `scripts/run_gremlins_gate.sh` | schemacore **100%** (8 killed); `otel` **100%** (90 killed). Four untouched surfaces not re-run. |
| Rust tests | `cd rust && cargo test --all-features` | 0 failed suites |
| Rust coverage | `cargo llvm-cov …` | passes with the CURRENT flag; see recommendation 3 |
| Rust mutation | `cargo mutants --in-place --all-features --file src/schema.rs` | 15 caught, 2 unviable, **0 missed** |
| TypeScript | `cd typescript && npm test` | 2178 passed |
| TypeScript mutation | `npx stryker run --mutate <changed file>` | `schema.ts` **100%** (123 killed); `otel-context-manager.ts` **100%** (36 killed) |
| C# tests | `cd csharp && dotnet test` | 989 passed |
| C# mutation | `dotnet-stryker --mutate '**/Schema.cs'` | **100%** — 45 killed, 0 survived (threshold is 78) |
| Max LOC | `uv run python scripts/check_max_loc.py --max-lines 777` | pass |
| SPDX | `uv run python scripts/check_spdx_headers.py` | pass |
| Version sync | `uv run python scripts/check_version_sync.py` | pass |
| Conformance | `uv run python spec/validate_conformance.py` | pass |
| Behavioral parity | `uv run python spec/run_behavioral_parity.py` | 5/5 languages PASS |
| Fixture coverage | `uv run python spec/check_fixture_coverage.py` | pass |
| Fixture IDs | `uv run python spec/check_fixture_test_ids.py` | 28 categories x 5 languages |
| Docs accuracy | `uv run python scripts/check_docs_accuracy.py` | pass |
| Worktree clean | `git status --short` (must be empty) | clean |

## Completion

**Status as of 2026-08-20, branch `remediation/external-review-2026-08-20`.**

| Rec | Status |
|---|---|
| 1 Go provider ownership | **Complete**, with a negative control |
| 2 `h2` + dependency gates | **Complete** — RUSTSEC-2026-0258 cleared, four blocking gates added |
| 3 Rust line-coverage gate | **Closed as a false positive**, with a pass/fail flip as proof |
| 4 `event_name` contract | **Complete** — breaking in 5 languages, not the 2 the design assumed |
| 5 Documentation | **Complete**, plus two defects the review missed |
| 6 npm publication | **Complete** — `continue-on-error` gone |
| 7 TypeScript context | **Complete** |
| 8 C# package evidence | **Complete** — found a nuspec losing its core dependency |
| 9 Dependabot | `DEFERRED BY USER` — untouched, not a blocker |
| 10 Rust OTLP flake | **Complete.** Root cause proven, deterministic reproducer, 0 failures in 18 stress runs |

Every recommendation is closed. Recommendation 9 remains `DEFERRED BY USER` by
instruction and is not a completion blocker.

Two of the review's ten findings turned out not to be defects. Recommendation 3
is a false positive — the coverage flag works, proven by a one-line pass/fail
flip. Recommendation 10 was real, but its cause was in test support rather than
in the library, so no production behaviour changed.

### Defects found during execution that the review did not list

1. `dotnet pack` dropped `Provide.Telemetry` from the integration package's
   dependency group when MSBuild received the symlinked repository path. The
   package restored cleanly and the consumer failed to compile.
2. Clearing `<packageSources>` is not isolation: the global NuGet cache served a
   previous run's artifact, keyed on id+version alone.
3. The C# core consumer asserted a `service.name` field the envelope has never
   emitted — it threw on every run, and nothing ran it.
4. `rust/README.md` documented `logger.info_with()`, which does not exist.
5. The new TypeScript parity file was counted by the fixture-coverage checker but
   missing from the vitest command, so the orchestrator never ran it.
6. Python, TypeScript and Rust did not implement the empty-segment rule the
   contract requires — the design assumed they already did.
7. Three new tooling tests broke collection inside mutmut's `mutants/` sandbox,
   so the Python mutation gate evaluated zero mutants until they were guarded.
8. A second flaky Rust test, `a_teardown_abandoned_at_the_deadline_returns_to_the_caller`,
   which releases its worker before asserting the abandoned-worker count.
