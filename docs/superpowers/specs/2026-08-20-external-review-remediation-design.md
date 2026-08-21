# External Review Remediation Design

> **Revision 2 (2026-08-20).** Revised after an internal review of revision 1.
> Changes: the `event_name` contract is now labelled a breaking change with an
> explicit per-entry-point scope; `spec/telemetry-api.yaml` is added as a
> changed artifact; a second C# defect (`ValidateEventName` ignores strict mode)
> is added to scope; the `h2` advisory is made evidence-first instead of
> asserted; mutation gates are added to the verification contract; the npm fix
> now names the `continue-on-error` removal; the Rust coverage fix now requires
> proving the current flag inert before replacing it; the TypeScript finding is
> corrected (`@opentelemetry/context-async-hooks` is already a declared peer
> dependency); workstream C is split; the plan directory is unified; and the
> vulnerability-exception mechanism is given a file, an owner, and an expiry.

## Purpose

This remediation closes the actionable findings from the 2026-08-20
five-language code and architecture review. It preserves the repository's
existing public shape — with one deliberate, documented exception in
[Event-name behavior](#event-name-behavior) — while making provider ownership
safe, cross-language contracts executable, quality and security gates
falsifiable, release failures honest, and shipped documentation accurate.

The work is tracked by one umbrella checklist and implemented through six
focused plans. Recommendation 9, automated dependency-update pull requests,
remains visible in the checklist but is explicitly deferred and makes no
Dependabot configuration changes.

## Scope

The implementation covers these recommendations:

1. Correct Go OpenTelemetry global-provider ownership and late host replacement.
2. Upgrade the vulnerable Rust `h2` dependency and add blocking dependency
   vulnerability checks for Python, TypeScript, Rust, and C#.
3. Make the Rust line-coverage gate actually enforce 100 percent.
4. Standardize `event_name` behavior across all five languages.
5. Correct shipped documentation and broaden executable documentation checks.
6. Stop masking arbitrary npm publication failures.
7. Make TypeScript's Node async-context dependency and degradation observable.
8. Verify both C# NuGet packages as installed artifacts from a clean local feed.
9. Record automated dependency-update pull requests as deferred.
10. Investigate the Rust OTLP export-test failure under a root-cause-only policy.

## Non-goals

- Do not enable Dependabot or another automated update bot as part of this work.
- Do not broaden public APIs. The TypeScript degraded state is exposed through
  the existing `setSetupError` mechanism and adds no new public status fields.
- Do not change the established strict event-segment grammar
  (`^[a-z][a-z0-9_]*$`).
- Do not change `Event()` / `event()` DAS/DARS segment-count behavior in any
  language. See [Entry-point scope](#entry-point-scope).
- Do not replace credentialed OpenObserve tests; keep them as live backend
  verification in addition to credential-free wire tests.
- Do not quarantine, ignore, retry, or lengthen sleeps around the Rust flaky test.
- Do not perform unrelated refactors while touching lifecycle or CI code.

## Confirmed Contract Decisions

### Event-name behavior

`event_name` and its language-specific spellings use this shared contract:

- Relaxed mode accepts one or more segments, every segment non-empty, and
  performs no segment grammar validation.
- Strict mode accepts three through five segments, inclusive.
- Every strict segment must match `^[a-z][a-z0-9_]*$`.
- Zero segments always fail. An empty segment always fails, in both modes.

Python, TypeScript, and Rust already implement this behavior
(`src/provide/telemetry/schema/events.py:110-126`). Go and C# will be changed to
match it. Shared behavioral fixtures make the count and grammar rules executable
rather than relying on symbol-presence conformance.

#### This is a breaking change for Go and C#

Go enforces 3–5 segments unconditionally, regardless of strict mode
(`go/internal/schemacore/schema.go:35-38`). C# does the same
(`csharp/src/Provide.Telemetry/Schema.cs:62-79`). Adopting the shared contract
**removes** a rejection that Go and C# callers get today in relaxed mode: after
this change, `EventName("startup")` succeeds where it previously raised.

This is a deliberate loosening in the permissive direction, chosen so that all
five languages share one contract rather than two. It is not a silent change:

- `CHANGELOG.md` must carry a `Changed`/`BREAKING` entry naming Go and C#, the
  old behavior, the new behavior, and the migration (set strict mode to restore
  count enforcement).
- `go/README.md` and `csharp/README.md` must state the relaxed-mode rule.
- The `VERSION` bump that carries this change is a minor bump on a `0.x` line
  and must be recorded in the release notes as behavior-affecting.

#### Entry-point scope

Each language exposes three distinct entry points with two distinct count
rules. Only the second and third change:

| Entry point | Rule today | Rule after | Changes? |
|---|---|---|---|
| `Event(...)` / `event(...)` — DAS/DARS record builder | exactly 3 or 4 segments, always | exactly 3 or 4 segments, always | **No** |
| `EventName(...)` / `event_name(...)` — variadic name builder | Go/C#: 3–5 always. Python/TS/Rust: relaxed 1+, strict 3–5 | relaxed 1+ non-empty, strict 3–5 | Go, C# |
| `ValidateEventName(name)` — dotted-string validator | Go: 3–5 always. C#: 3–5 **and grammar, always** | relaxed 1+ non-empty, strict 3–5 + grammar | Go, C# |

`Event()` keeps its own stricter rule because DAS/DARS is a positional record
shape, not a name; a 1-segment `Event()` has no domain/action/status to fill.

#### Second C# defect: `ValidateEventName` ignores strict mode

`csharp/src/Provide.Telemetry/Schema.cs:81-93` applies the segment regex on
every call, never reading `GetStrictSchema()`. Its sibling `EventName` at
`:62-79` gates the same regex on strict mode. This divergence is inside C# and
is independent of the cross-language count change; both are fixed under
recommendation 4.

#### Dotted-string versus variadic semantics

"Zero segments" is only reachable through the variadic entry points. String
splitting never yields zero elements: `"".Split(".")` yields one empty element.
The contract is therefore expressed for both shapes:

- Variadic with no arguments → fail (zero segments).
- Dotted string `""` → one empty segment → fail (empty segment).
- Dotted string `"a..b"` → three segments, one empty → fail (empty segment).
- Dotted string `"startup"` in relaxed mode → one non-empty segment → pass.

#### Canonical spec must change too

`spec/telemetry-api.yaml:969-973` encodes a single ruleset:

```yaml
event_schema:
  segment_pattern: "^[a-z][a-z0-9_]*$"
  min_segments: 3
  max_segments: 4
  separator: "."
```

That block cannot express the relaxed/strict split, and its `max_segments: 4`
already contradicts the 3–5 `EventName` range every language ships. It is
restructured to name both modes and both entry points explicitly. The change to
`spec/telemetry-api.yaml` is in scope for recommendation 4 and must land in the
same commit as the Go and C# behavior change, so `validate_conformance.py` never
runs against a spec that disagrees with all five implementations.

### Dependency vulnerability policy

Vulnerability gates cover production and development dependencies. The current
TypeScript development findings must be upgraded away before the all-dependency
gate becomes blocking. A scan that inventories zero packages is a failure, not a
successful clean result.

No dependency vulnerability scanner exists in the repository today: no
`cargo-audit`, `cargo-deny`, `pip-audit`, `npm audit`, or
`dotnet list package --vulnerable` invocation appears in `.github/workflows/`,
`ci/`, or `scripts/`. Every gate below is new.

The gate design is ecosystem-native:

- Python audits dependencies exported from the committed `uv.lock`, not the
  repository directory as an installation path.
- TypeScript audits the complete npm dependency graph.
- Rust audits `Cargo.lock` and blocks RustSec advisories unless a reviewed,
  expiring exception names the advisory and rationale.
- C# audits transitive NuGet dependencies for every project in the solution.
- Go retains its existing `gosec` and `govulncheck` controls; no replacement is
  needed.

#### Interim policy while TypeScript findings exist

Each language's gate lands **already blocking**. TypeScript is the one surface
with known outstanding development findings, so its ordering is fixed: upgrade
the offending development dependencies first, then land the gate blocking in the
same plan. A non-blocking "warn only" phase is not used, because a gate that
cannot fail is the exact failure mode recommendation 6 exists to remove.

#### Exception mechanism

Rust exceptions live in `rust/deny.toml` under `[advisories].ignore`, one entry
per advisory, each carrying an inline comment with the rationale and an
explicit `expires` date no more than 90 days out. `scripts/check_advisory_expiry.py`
fails the build on any entry past its expiry or missing a rationale comment, so
an exception cannot outlive its review. The reviewer is whoever approves the pull
request adding the entry; the rationale comment names the upstream issue or the
blocking constraint. No other ecosystem gets an exception mechanism in this
work — Python, TypeScript, and C# findings are fixed by upgrading.

#### The `h2` advisory is recorded, not asserted

`rust/Cargo.lock:514-516` pins `h2 0.4.15`. This design does **not** name the
advisory ID or the patched version, because neither was captured in the review
record. The plan's first step is to run `cargo audit` against the committed
lockfile and write the exact advisory ID, affected range, and patched version
into the checklist as evidence. Only then is the upgrade performed.

If the patched version is not reachable under the current dependency
constraints — that is, if it requires bumping `hyper`, `reqwest`, or an
`opentelemetry-otlp` transitive — that is a scope expansion. Record it in the
checklist, stop, and raise it rather than silently widening the change.

### Rust flake acceptance rule

The Rust investigation must preserve the original failure evidence, reproduce
the failure statistically, and build a deterministic fault-injected reproducer
before changing production behavior. Lifecycle or generation instrumentation
must demonstrate the root cause. The regression test must fail without the fix
and pass with it, including a temporary revert of the fix as the negative
control. Parallel and serial stress runs must both pass afterward.

If no root cause can be demonstrated, no speculative production change is
allowed. The investigation is recorded as inconclusive with its commands,
observations, and rejected hypotheses.

## Workstream Design

### Workstream A: Runtime contracts

This workstream contains recommendations 1 and 4.

#### Go provider ownership

`go/otel/backend.go:33-35` tracks ownership as three booleans
(`_weSetTracerGlobal`, `_weSetMeterGlobal`, `_weSetLoggerGlobal`). At shutdown,
`_resetGlobalsWeSet()` (`go/otel/backend.go:217-231`) overwrites the global with
an API no-op whenever its boolean is set — without checking whether the global
still holds the provider Provide installed. A host that calls
`otel.SetTracerProvider(hostTP)` *after* our setup therefore has its provider
silently replaced by a no-op when `ShutdownTelemetry` runs.

The backend will distinguish three identities: the host provider present before
installation, the exact provider installed by Provide, and the provider
currently registered globally. Shutdown may alter the global only when it still
points to the exact provider installed by Provide. A host replacement made after
setup must remain globally registered and must not be shut down.

Note the ordering hazard: `Shutdown` (`go/otel/backend.go:205-212`) nils
`_otelTracerProvider` and friends *before* calling `_resetGlobalsWeSet()`. The
identity comparison must use pointers captured before the nil-out, not the
fields.

Conflict warnings must use identity and ownership evidence rather than treating
every concrete SDK provider as Provide-owned. Today
`_warnIfTracerProviderConflict` (`go/otel/providers.go:19-36`) returns without
warning whenever the incumbent type-asserts to `*sdktrace.TracerProvider`, so a
host SDK provider is mistaken for our own and the overwrite goes unannounced.

#### Event-name contract

Shared fixture cases define relaxed and strict count behavior. The existing
fixture infrastructure is extended, not replaced:

- `spec/behavioral_fixtures.yaml` gains an `event_name_contract` category
  alongside the existing `event_dars` and `schema_strict_mode` categories.
- `spec/fixture_test_ids.yaml` maps each new case ID to its per-language test.
- `spec/check_fixture_coverage.py` and `spec/check_fixture_test_ids.py` gate it.
- `spec/run_behavioral_parity.py` executes it across all five languages.

Every language must consume or explicitly assert every new fixture case, and the
parity tooling must verify per-case execution rather than accepting a
category-name mention.

### Workstream B: Security and quality gates

This workstream contains recommendations 2 and 3.

The Rust lockfile is updated to the patched `h2` release identified by the
recorded `cargo audit` evidence. New vulnerability jobs run deterministic scans
against committed dependency state. Gate tests prove each scanner inventories a
non-zero expected dependency set and that a simulated finding produces a
failure.

For coverage, `.github/workflows/ci-rust.yml:102` currently passes
`--fail-uncovered-lines 0` alongside `--fail-under-functions 100`. The claim
that this flag is inert is **not** assumed. The work is ordered:

1. Build a controlled coverage fixture with a known-uncovered line.
2. Run the current command against it and record whether it passes. If it fails
   as it should, recommendation 3 is closed as a false positive with that
   evidence, and no flag change is made.
3. Only if the current command passes on an under-covered report, replace the
   argument with an explicit `--fail-under-lines 100` and prove the fixture now
   fails.

Whatever the outcome, `CLAUDE.md` documents the same command verbatim and must
be updated in lockstep so the docs-accuracy gate and the workflow do not drift.

### Workstream C1: npm release and TypeScript context

This workstream contains recommendations 6 and 7. It is split from
documentation so it does not bundle unrelated languages into one commit, per
this design's own commit rule.

#### npm publication

`.github/workflows/release.yml:255` sets `continue-on-error: true` on the
`publish-npm` job. **Removing that line is part of the fix**, not an
afterthought: every other change in this recommendation is inert while the job
cannot fail.

The job will remain idempotent without making the whole job non-blocking. It
will query the registry for the exact version before publishing: an existing
version is a documented successful no-op, while authentication, network,
package, provenance, and new-version publication failures remain fatal. A
postcondition verifies the requested version exists.

#### TypeScript async context

`@opentelemetry/context-async-hooks` is **already** a declared
`peerDependency` in `typescript/package.json`. The gap is not a missing
dependency; it is that the dependency is undocumented in the README's install
instructions, and that `typescript/src/otel.ts:106-108` swallows every failure
in a bare `catch {}` labelled "Not a Node.js environment or peer dep not
installed — skip silently."

Provider registration will distinguish an intentionally unsupported environment
from a missing or failed Node context manager. The discriminator is explicit:

- The dynamic import rejects with `code === 'ERR_MODULE_NOT_FOUND'` (or a
  message naming the specifier) **and** the runtime is Node → peer dependency
  missing → actionable message.
- The import resolves but `new AsyncLocalStorageContextManager()`,
  `.enable()`, or `context.setGlobalContextManager()` throws → context manager
  failed → actionable message.
- The runtime is not Node (no `process.versions.node`) → intentionally
  unsupported → silent, no message.

The Node failure path will set a stable, actionable context-manager message
through the existing `setSetupError` mechanism
(`typescript/src/health.ts:147-149`), making it visible from both
`getHealthSnapshot().setupError` (`typescript/src/health.ts:113-142`) and
`getRuntimeStatus().setupError` (`typescript/src/runtime.ts:254`), and emit a
one-time warning. A later successful context-manager installation may clear its
own prior message but must not clear an unrelated setup error. This remains
fail-open for signal export and adds no new public status fields. Environments
that intentionally use the browser/no-op implementation remain silent.

### Workstream C2: Documentation

This workstream contains recommendation 5 and runs after the behavior changes it
documents.

Documentation corrections cover, at minimum, these confirmed defects:

| File | Defect | Evidence |
|---|---|---|
| `go/README.md:13`, `go/README.md:268` | claims "Go 1.22+" | `go/go.mod:3` and `go/otel/go.mod:3` both declare `go 1.26.0` |
| `rust/README.md:16` | `provide-telemetry = "0.3"` | `VERSION` is `0.8.0`; `rust/Cargo.toml:7` is `0.8.0` |
| `rust/README.md:24-36` | `setup_telemetry()` / `shutdown_telemetry()` shown with no arguments | real signatures are `setup_telemetry(Option<TelemetryConfig>) -> Result<TelemetryConfig, TelemetryError>` (`rust/src/setup.rs:37`) and `shutdown_telemetry(Option<f64>) -> Result<(), TelemetryError>` (`rust/src/setup.rs:102`) — the README snippet does not compile |
| `docs/guide/capability-matrix.md:61-65` | "C# is the one language whose OTLP rows have no blocking CI evidence" | `csharp/tests/Provide.Telemetry.OpenTelemetry.Tests/WireDeliveryTests.cs` and `FakeOtlpCollector.cs` are credential-free and run in `ci-csharp.yml` |
| `.github/workflows/ci-spec.yml:49`, `ci-contracts.yml:73`, `ci-contracts.yml:80`, `ci-contracts.yml:116`, `ci-surface.yml:64`, `ci-surface.yml:68` | comments say "four languages" / "4 languages" | five languages ship |
| `scripts/check_docs_accuracy.py:15` | `MIN_MUTATION_SCORE = 95.0` | `CLAUDE.md` states 100 percent kill is enforced, not targeted |
| Go and C# READMEs | no statement of relaxed-mode event-name behavior | changed by recommendation 4 |

`scripts/check_docs_accuracy.py:11` currently scans
`DOC_PATHS = ("README.md", "docs", "examples/README.md")`, which excludes every
language README and contributor guidance. It will be widened to include
`go/README.md`, `rust/README.md`, `typescript/README.md`, `csharp/README.md`,
and `CONTRIBUTING.md`.

Executable snippet tests will compile or run the primary quick starts where
practical. The Rust README snippet above is the proof case: it is the defect a
snippet test catches automatically and a human reviewer misses.

### Workstream D: C# package evidence

This workstream contains recommendation 8.

The existing `WireDeliveryTests` and `FakeOtlpCollector` already provide
blocking, credential-free OTLP/HTTP delivery evidence for logs, traces, and
metrics. They remain the wire-level test and the capability matrix will be
corrected to cite them.

The missing evidence is artifact consumption. CI will pack both NuGet packages
into a temporary local feed, create or use clean consumer projects with no
`ProjectReference`, install exact-version packages from that feed, build them,
and run them. The OTel consumer must prove that installing the integration
package plus registration activates the backend; the core-only consumer must
prove the BCL-only boundary remains intact.

### Workstream E: Rust flake investigation

This workstream contains recommendation 10 and follows the confirmed acceptance
rule. It is isolated from other behavior changes so dependency or coverage work
cannot be mistaken for the fix. The candidate surfaces are
`rust/tests/otlp_collector_test.rs`, `rust/tests/otlp_runtime_test.rs`, and
`rust/tests/shutdown_unreachable_endpoint_test.rs`; the plan's first step
identifies which one actually failed and preserves that output verbatim.

Investigation artifacts must identify every stress command, seed or schedule
control, lifecycle generation, collector endpoint, and outstanding drain worker
involved in a failure.

## Checklist and Plan Structure

The umbrella checklist and all focused plans live in one directory,
`docs/superpowers/plans/`, matching where this design's spec lives
(`docs/superpowers/specs/`). Revision 1 split them across `docs/plans/` and
`docs/superpowers/plans/`; that split is dropped.

Umbrella checklist:

`docs/superpowers/plans/2026-08-20-external-review-remediation-checklist.md`

It contains all ten numbered recommendations, with recommendation 9 marked
deferred, links to the six focused plans, dependencies between workstreams, and
the exact verification evidence required before an item is checked.

The six focused plans use checkbox-based, test-driven steps:

1. `2026-08-20-runtime-contract-remediation.md` — workstream A
2. `2026-08-20-security-and-coverage-gates.md` — workstream B
3. `2026-08-20-npm-release-and-typescript-context.md` — workstream C1
4. `2026-08-20-documentation-accuracy.md` — workstream C2
5. `2026-08-20-csharp-package-verification.md` — workstream D
6. `2026-08-20-rust-export-flake-investigation.md` — workstream E

## Execution Order

1. Capture a clean baseline and preserve the original Rust failure evidence.
2. Complete security and coverage gates, including the `h2` update (plan 2).
3. Complete Go ownership and shared `event_name` behavior (plan 1).
4. Complete npm release handling and TypeScript context observability (plan 3).
5. Complete C# package artifact verification (plan 5).
6. Run the isolated Rust flake investigation (plan 6).
7. Correct and regenerate documentation after behavior and evidence stabilize
   (plan 4).
8. Run the complete repository verification matrix and update the umbrella
   checklist with measured evidence.

Small commits are required at independently verifiable boundaries. A workstream
must not bundle unrelated languages merely to reduce commit count.

## Testing and Falsifiability

Every behavioral or gate change follows red-green verification:

- Add a focused failing regression or falsifiability test.
- Run it and preserve the expected failure.
- Implement the smallest change that satisfies the test.
- Run the focused test and the owning language's static/build/test gates.
- Temporarily weaken or revert the implementation when necessary to prove the
  gate can detect the targeted regression.
- Restore the implementation and rerun the final gate.

### Mutation gates are part of the definition of done

This repository enforces a 100 percent mutation kill score in every language,
and it is the gate most likely to reject this work. New branches introduced
here — Go provider-identity comparisons, the TypeScript failure discriminator,
the C# strict-mode read, the relaxed/strict count split — are exactly the shape
that survives naive tests. Each plan that changes source code must run its
language's mutation gate before its final commit:

| Language | Command | Note |
|---|---|---|
| Go | `scripts/run_gremlins_gate.sh` over the affected surface | `otel` module needs `GOTOOLCHAIN=go1.26.1` locally |
| Python | `uv run python scripts/run_mutation_gate.py --max-children 2 --min-mutation-score 95` | zero survivors, timeouts, suspicious, and no-tests results |
| Rust | `cargo mutants --in-place --all-features --shard 1/8` | `--in-place` is required; see `CLAUDE.md` |
| TypeScript | `npx stryker run --concurrency 2` and `npx stryker run --concurrency 2 -c stryker.otel.config.mjs` | |
| C# | `dotnet stryker` with `csharp/stryker-config.json` | |

Run these one at a time. Two concurrently will exhaust memory on a workstation.

Cross-language contract changes additionally run configuration, fixture-ID,
behavioral parity, runtime parity, contract-probe, and full language suites.
CI workflow changes are syntax-checked and tested through repository checker
tests or local workflow simulations where credentials are not required.

## Failure Handling and Rollback

- Provider shutdown must fail safely by leaving a host-owned global untouched.
- Vulnerability scanners must fail on collection errors or empty inventories;
  they may not convert scanner failure into a clean result.
- npm idempotency may suppress only a positively confirmed existing version, and
  only after `continue-on-error` is removed.
- TypeScript context-manager failure remains fail-open for telemetry but becomes
  observable.
- C# package tests use a temporary feed and exact versions so public registries
  cannot hide a broken artifact.
- The Rust flake investigation changes no production behavior without a proven
  root cause.

Each focused plan ends with a dedicated commit and a worktree-cleanliness check.
If a workstream must be rolled back, its commits can be reverted without
removing the checklist or invalidating independent workstreams. The one
exception is recommendation 4: the `spec/telemetry-api.yaml` change and the
Go/C# behavior change must revert together or conformance breaks.

## Completion Criteria

The remediation is complete when recommendations 1-8 and 10 have their required
tests and verification evidence recorded in the umbrella checklist, all standard
language and shared gates pass, every affected language's mutation gate passes,
dependency scans have non-empty inventories and no unapproved findings, artifact
consumers run successfully, documentation matches observed behavior, the
breaking `event_name` change is recorded in `CHANGELOG.md`, and the tracked
worktree is clean.

Recommendation 9 remains unchecked with status `DEFERRED BY USER`; it is not a
completion blocker for this remediation.
