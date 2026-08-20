# External Review Remediation Design

## Purpose

This remediation closes the actionable findings from the 2026-08-20
five-language code and architecture review. It preserves the repository's
existing public shape while making provider ownership safe, cross-language
contracts executable, quality and security gates falsifiable, release failures
honest, and shipped documentation accurate.

The work is tracked by one umbrella checklist and implemented through five
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
- Do not broaden public APIs unless required to expose the TypeScript degraded
  state through an existing runtime-status or health mechanism.
- Do not change the established strict event-segment grammar.
- Do not replace credentialed OpenObserve tests; keep them as live backend
  verification in addition to credential-free wire tests.
- Do not quarantine, ignore, retry, or lengthen sleeps around the Rust flaky test.
- Do not perform unrelated refactors while touching lifecycle or CI code.

## Confirmed Contract Decisions

### Event-name behavior

`event_name` and its language-specific spellings use this shared contract:

- Relaxed mode accepts one or more non-empty segments and performs no segment
  grammar validation.
- Strict mode accepts three through five segments, inclusive.
- Every strict segment must match `^[a-z][a-z0-9_]*$`.
- Zero segments always fail.

Python, TypeScript, and Rust already implement this behavior. Go and C# will be
changed to match it. Shared behavioral fixtures will make the count and grammar
rules executable rather than relying on symbol-presence conformance.

### Dependency vulnerability policy

Vulnerability gates cover production and development dependencies. The current
TypeScript development findings must be upgraded away before the all-dependency
gate becomes blocking. A scan that inventories zero packages is a failure, not a
successful clean result.

The gate design is ecosystem-native:

- Python audits dependencies exported from the committed `uv.lock`, not the
  repository directory as an installation path.
- TypeScript audits the complete npm dependency graph.
- Rust audits `Cargo.lock` and blocks RustSec advisories unless a reviewed,
  expiring exception names the advisory and rationale.
- C# audits transitive NuGet dependencies for every project in the solution.
- Go retains its existing `gosec` and `govulncheck` controls; no replacement is
  needed.

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

For Go provider ownership, the backend will distinguish three identities:
the host provider present before installation, the exact provider installed by
Provide, and the provider currently registered globally. Shutdown may alter the
global only when it still points to the exact provider installed by Provide.
A host replacement made after setup must remain globally registered and must not
be shut down. Conflict warnings must use identity and ownership evidence rather
than treating every concrete SDK provider as Provide-owned.

For `event_name`, shared fixture cases define relaxed and strict count behavior.
Go and C# implementations change to match the confirmed contract. Every language
must consume or explicitly assert every new fixture case, and the parity tooling
must verify case execution rather than accepting a category-name mention.

### Workstream B: Security and quality gates

This workstream contains recommendations 2 and 3.

The Rust lockfile is updated to a non-vulnerable `h2` release allowed by the
current dependency constraints. New vulnerability jobs run deterministic scans
against committed dependency state. Gate tests prove each scanner inventories a
non-zero expected dependency set and that a simulated finding produces a
failure.

The Rust coverage command replaces the ineffective uncovered-line argument with
an explicit 100-percent line threshold while retaining 100-percent function
coverage. A checker test or controlled coverage fixture must prove a report below
100 percent is rejected, preventing another semantically inert flag from passing.

### Workstream C: Documentation, npm release, and TypeScript context

This workstream contains recommendations 5, 6, and 7.

Documentation corrections cover Go's supported version and fallback semantics,
Rust installation and lifecycle signatures, the strict segment grammar, current
C# coverage claims, mutation-threshold language, C# wire-test evidence, and any
workflow comments that still describe four languages. The documentation checker
will include every shipped language README and contributor guidance. Executable
snippet tests will compile or run the primary quick starts where practical.

The npm publication job will remain idempotent without making the whole job
non-blocking. It will query the registry for the exact version before publishing:
an existing version is a documented successful no-op, while authentication,
network, package, provenance, and new-version publication failures remain fatal.
A postcondition verifies the requested version exists.

TypeScript documentation will include `@opentelemetry/context-async-hooks` for
Node async propagation. Provider registration will distinguish an intentionally
unsupported environment from a missing or failed Node context manager. The
Node failure path will set a stable, actionable context-manager message through
the existing `setSetupError` mechanism, making it visible from both
`getHealthSnapshot().setupError` and `getRuntimeStatus().setupError`, and emit a
one-time warning. A later successful context-manager installation may clear its
own prior message but must not clear an unrelated setup error. This remains
fail-open for signal export and adds no new public status fields. Environments
that intentionally use the browser/no-op implementation remain silent.

### Workstream D: C# package evidence

This workstream contains recommendation 8.

The existing `WireDeliveryTests` and `FakeOtlpCollector` already provide blocking,
credential-free OTLP/HTTP delivery evidence for logs, traces, and metrics. They
remain the wire-level test and the capability matrix will be corrected to cite
them.

The missing evidence is artifact consumption. CI will pack both NuGet packages
into a temporary local feed, create or use clean consumer projects with no
`ProjectReference`, install exact-version packages from that feed, build them,
and run them. The OTel consumer must prove that installing the integration
package plus registration activates the backend; the core-only consumer must
prove the BCL-only boundary remains intact.

### Workstream E: Rust flake investigation

This workstream contains recommendation 10 and follows the confirmed acceptance
rule. It is isolated from other behavior changes so dependency or coverage work
cannot be mistaken for the fix. Investigation artifacts must identify every
stress command, seed or schedule control, lifecycle generation, collector
endpoint, and outstanding drain worker involved in a failure.

## Checklist and Plan Structure

The umbrella checklist will live at:

`docs/plans/2026-08-20-external-review-remediation-checklist.md`

It will contain all ten numbered recommendations, with recommendation 9 marked
deferred, links to the five focused plans, dependencies between workstreams, and
the exact verification evidence required before an item is checked.

The five focused plans will live under `docs/superpowers/plans/` and use
checkbox-based, test-driven steps:

1. `2026-08-20-runtime-contract-remediation.md`
2. `2026-08-20-security-and-coverage-gates.md`
3. `2026-08-20-docs-release-and-typescript-context.md`
4. `2026-08-20-csharp-package-verification.md`
5. `2026-08-20-rust-export-flake-investigation.md`

## Execution Order

1. Capture a clean baseline and preserve the original Rust failure evidence.
2. Complete security and coverage gates, including the `h2` update.
3. Complete Go ownership and shared `event_name` behavior.
4. Complete TypeScript context observability and npm release handling.
5. Complete C# package artifact verification.
6. Run the isolated Rust flake investigation.
7. Correct and regenerate documentation after behavior and evidence stabilize.
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

Cross-language contract changes additionally run configuration, fixture-ID,
behavioral parity, runtime parity, contract-probe, and full language suites.
CI workflow changes are syntax-checked and tested through repository checker
tests or local workflow simulations where credentials are not required.

## Failure Handling and Rollback

- Provider shutdown must fail safely by leaving a host-owned global untouched.
- Vulnerability scanners must fail on collection errors or empty inventories;
  they may not convert scanner failure into a clean result.
- npm idempotency may suppress only a positively confirmed existing version.
- TypeScript context-manager failure remains fail-open for telemetry but becomes
  observable.
- C# package tests use a temporary feed and exact versions so public registries
  cannot hide a broken artifact.
- The Rust flake investigation changes no production behavior without a proven
  root cause.

Each focused plan ends with a dedicated commit and a worktree-cleanliness check.
If a workstream must be rolled back, its commits can be reverted without
removing the checklist or invalidating independent workstreams.

## Completion Criteria

The remediation is complete when recommendations 1-8 and 10 have their required
tests and verification evidence recorded in the umbrella checklist, all standard
language and shared gates pass, dependency scans have non-empty inventories and
no unapproved findings, artifact consumers run successfully, documentation
matches observed behavior, and the tracked worktree is clean.

Recommendation 9 remains unchecked with status `DEFERRED BY USER`; it is not a
completion blocker for this remediation.
