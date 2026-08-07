# Five-Language Rigorous Parity Design

**Date:** 2026-08-04

**Status:** Approved

**Target release:** 0.8

## Purpose

Bring the Python, TypeScript, Go, Rust, and C# SDKs to one executable
behavioral contract. The work closes the findings from the repository-wide
review at commit `4d408d3` and replaces static or textual parity claims with
tests that exercise public behavior.

The canonical contract takes precedence over legacy behavior. This project
will not preserve obsolete C# environment names, dotted local-log fields, or
disconnected public capability surfaces.

## Current State

Python, TypeScript, Go, and Rust pass the existing behavioral, output, runtime,
and contract probes. Their implementations still contain isolated lifecycle,
context, governance, and hardening gaps.

C# appears in `spec/telemetry-api.yaml` and the default parity runner, but the
strict fixture-ID gate covers only four languages. C# also combines core and
OpenTelemetry dependencies in one package and lacks several behaviors claimed
by the shared contract.

The implementation must confirm each reported gap before changing production
code. A task closes with no production change when a search and characterization
test prove that the current implementation already meets the contract.

## Goals

1. Give all five SDKs one canonical configuration vocabulary, local record
   envelope, policy order, lifecycle model, and governance behavior.
2. Require executable fixture evidence for every required capability and
   language.
3. Fix the security, correlation, concurrency, receipt, hardening, and
   lifecycle findings identified by the review.
4. Split C# into an OTel-free core package and an OpenTelemetry integration
   package.
5. Raise C# quality gates to the owned-code standard applied to the other
   implementations.
6. Make documentation, examples, CI, packaging, and release metadata describe
   five supported SDKs.

## Non-Goals

- Preserve legacy C# environment aliases or dotted local log keys.
- Preserve pre-1.0 signatures that cannot express truthful lifecycle or receipt
  outcomes.
- Standardize language syntax when idiomatic APIs express the same behavior.
- Own or shut down providers installed by the host application.
- Treat static symbol presence, source comments, or category names as
  behavioral evidence.

## Architecture

The shared runtime model is:

```text
canonical spec and fixtures
            |
      language facade
            |
 immutable validated config snapshot
            |
 consent -> sampling -> backpressure
            |
 recursive hardening -> classification and PII
            |
 receipt sink -> canonical local record
            |
 optional backend export -> health accounting
            |
       release ticket
```

Each SDK owns an idiomatic facade and runtime implementation. The spec defines
observable behavior, field names, defaults, ordering, failure categories, and
result shapes. Tests compare those boundaries without requiring identical
internal types.

### Subproject 1: Executable Contract Foundation

`spec/telemetry-api.yaml` remains the canonical API and configuration source.
The fixture system will cover five languages through resolvable test IDs.

The contract foundation will define:

- canonical config names, types, defaults, validation, and applicability;
- canonical snake_case local log fields;
- resource attribute precedence;
- percent-decoded OTLP header parsing with literal `+` preservation;
- recursive hardening and PII semantics;
- receipt payload and HMAC-SHA256 vectors;
- lifecycle generation, provider ownership, and deadline behavior;
- resilience attempts, health transitions, and circuit states.

`check_fixture_coverage.py` may remain a discovery report, but it cannot satisfy
the release gate. `check_fixture_test_ids.py` must resolve C# tests or probes in
the same way it resolves the other languages. Literal fixture cases must drive
the tests.

### Subproject 2: Existing Runtime Correctness

#### TypeScript

- Initialize `AsyncLocalStorage` through an ESM-safe mechanism for logger,
  propagation, and trace context.
- Preserve context until asynchronous callbacks settle.
- Test the packed `dist` artifact under Node ESM.
- Replace the receipt hash construction with standard HMAC-SHA256.
- Deliver production receipts to a caller-provided sink without retaining a
  library-owned production buffer.

#### Go

- Build immutable config and logger generations during reconfiguration.
- Publish runtime and logger state through an atomic snapshot.
- Prevent handlers from retaining pointers to mutable configuration.
- Sanitize typed maps, slices, arrays, and supported structs with cycle and
  depth protection.
- Add targeted race tests for logging during update, reconfigure, and shutdown.

#### Python

- Use one lifecycle coordinator for setup, update, reconfigure, and shutdown.
- Publish a new generation only after policies and logging have applied.
- Return the active snapshot from repeated setup calls without parsing an
  unused argument or changed environment.
- Add deterministic interleaving tests for lifecycle operations.

#### Rust

- Implement every config field claimed as shared or mark the field's
  applicability in the canonical schema.
- Apply recursive hardening before local and OTel sinks.
- Retain existing RAII context restoration.
- Remove or feature-gate dependencies that baseline builds do not use.

### Subproject 3: Cross-Language Governance and Hardening

Every signal path must run hardening before any renderer, capture buffer,
receipt, or exporter receives the record.

Hardening enforces:

- maximum attribute count;
- maximum string value length;
- maximum nesting depth;
- control-character handling required by the fixtures;
- cycle protection for runtimes that accept reference graphs;
- preservation of required telemetry identity fields.

PII traversal must handle dictionaries and maps, arrays and slices, lists,
native JSON object and array values, and exported struct or public POCO fields.
Traversal unwraps interface, pointer, and nullable containers. A cycle or a
composite value that cannot be inspected becomes `"***"`; it cannot pass through
with uninspected content. Non-container scalar types use invariant string
conversion before length limits and value-based secret detection run.

Receipt signing uses lowercase HMAC-SHA256 over this UTF-8 payload:

```text
receipt_id|timestamp|field_path|action|original_hash
```

Receipt IDs use lowercase canonical UUID text. Timestamps use UTC RFC 3339 text
with exactly three fractional-second digits and a `Z` suffix. Actions are
lowercase contract enum values.

`original_hash` is lowercase SHA-256 over an RFC 8785 JSON Canonicalization
Scheme representation after normalization to the contract's JSON value model.
The model contains only null, booleans, finite IEEE-754 binary64 numbers,
Unicode strings, ordered arrays, and string-keyed objects. Unsupported or
non-finite scalar values normalize to invariant strings before
canonicalization. Shared vectors fix every input, including receipt ID and
timestamp, so every runtime must produce the same digest.

Production receipt delivery uses a caller-provided synchronous sink whose
`emit(receipt)` operation returns whether it accepted the receipt. The library
keeps no production receipt buffer. Enabling receipts outside test mode without
a sink raises a configuration error. Sink rejection or failure increments a
governance receipt-failure health counter and cannot recurse through the normal
telemetry logger. Test collectors remain test-only and have a fixed 1,024-entry
capacity.

### Subproject 4: C# Package and Runtime Reconstruction

The C# solution will publish two packages.

#### `Provide.Telemetry`

The core package contains:

- canonical config and validation;
- lifecycle facade and immutable runtime state;
- logging, fallback tracing, and fallback metrics;
- context, propagation, schema, sampling, backpressure, health, and SLO logic;
- PII, classification, consent, and receipts;
- a backend interface and backend registration boundary.

The core package has no OpenTelemetry, exporter, or Microsoft dependency
injection package references.

#### `Provide.Telemetry.OpenTelemetry`

The integration package contains:

- OpenTelemetry providers and resource construction;
- trace, metric, and log bridges;
- per-export resilience wrappers;
- provider ownership and host adoption;
- bounded concurrent flush and shutdown;
- backend registration helpers.

The integration depends on the core package. Core never references the
integration assembly.

#### C# behavioral requirements

- Canonical environment names replace legacy names.
- Setup rejects invalid sampling values, endpoints, limits, and retry counts.
- Local logs emit canonical snake_case fields only.
- Error events receive canonical fingerprints.
- Span disposal restores the prior trace context exactly once.
- Fallback and live metrics provide race-free value and sum snapshots.
- Recursive PII handles dictionaries, arrays, lists, JSON values, and public
  POCO fields.
- Resilience settings control real export attempts and update health state.
- Flush and shutdown share one absolute deadline across signal drains.
- Provider disposal occurs outside the lifecycle lock.
- Provider setup never mutates process-wide OTel environment variables.

## Runtime Contract

### Configuration and publication

Setup validates a complete snapshot before applying any state. Invalid config
raises the language's configuration error. Setup does not clamp invalid values.

The runtime publishes a generation after logging and policy subsystems accept
it. Repeated setup returns a defensive copy of the active generation. Update,
reconfigure, and shutdown cannot publish pieces from different generations.

### Context

Request, session, propagation, and trace context use runtime-native scoped
storage. Scope completion restores its predecessor. Async callbacks retain
their context until success or failure settles.

### Signal processing

Signals follow this order:

1. consent;
2. sampling;
3. backpressure acquisition;
4. recursive hardening;
5. classification and PII policy;
6. receipt emission;
7. local record creation;
8. optional backend export;
9. health accounting;
10. ticket release.

Each exit path releases its ticket. Sampling, consent, hardening, and queue
rejections increment the signal's dropped counter. Successful local emission
increments emitted. Export exceptions increment failures, each repeated attempt
increments retries, every completed attempt records latency, and breaker
transitions update state and open count.

### Export and lifecycle errors

Configuration errors fail setup. Export construction and transport failures may
degrade only when the signal's `fail_open` setting permits it. Health and runtime
status report the degradation.

Flush keeps providers installed and reports each signal as flushed, timed out,
failed, not installed, or not owned. Shutdown drains and detaches owned
providers. Both operations use one absolute deadline and start independent
signal drains together.

## Verification Design

### API evidence

- Compile a consumer project against each public package.
- Check facade exports and signatures.
- Keep static extraction as a fast preliminary check.

### Behavioral evidence

- Resolve every fixture category to an executable test or probe in all five
  languages.
- Load literal cases from shared fixtures.
- Compare canonical output, runtime probes, and contract probes across all five
  implementations.

### Concurrency and packaging evidence

- TypeScript runs ESM tests against the packed artifact.
- Go runs targeted reconfiguration and emission tests under `-race`.
- Python runs controlled lifecycle interleavings.
- Rust runs nested task and guard restoration tests.
- C# tests `AsyncLocal`, nested spans, concurrent instruments, provider drains,
  and both package consumer paths.

### Quality evidence

- C# owned code reaches 100% line and branch coverage.
- C# mutation testing rejects surviving owned-code mutants. Framework glue may
  use explicit reviewed exemptions with reasons.
- The existing language lint, type, coverage, mutation, LOC, licensing, and
  security gates remain active.
- A five-language config gate compares names, types, defaults, and
  applicability.

### Release evidence

- Test core-only and OTel-enabled packages.
- Compare canonical local log envelopes.
- Verify logs, traces, and metrics through a collector.
- Run consumer package tests from built artifacts.
- Validate documentation commands and version synchronization.
- Require a named test or probe for each `core` capability-matrix cell.

## TDD and Existing-Implementation Preflight

Before each production change:

1. Search for an existing implementation and its consumers.
2. Run or add a characterization test for the reported behavior.
3. If the behavior already satisfies the contract, record the evidence and
   remove or narrow the task.
4. Otherwise, add one failing test that names the break.
5. Confirm the test fails for the expected reason.
6. Implement the smallest production change that passes it.
7. Run the focused suite, then the language gate.

Generated config artifacts are exempt from hand-written TDD only when their
generator and generated-output check have failing tests first.

## Delivery Sequence

1. Five-language contract and fixture infrastructure.
2. TypeScript ESM context and receipt correctness.
3. Go immutable runtime state and recursive sanitization.
4. Python lifecycle generation and truthful setup.
5. Rust canonical config and recursive hardening.
6. C# core and OpenTelemetry package split.
7. C# governance, context, metrics, logging, and config parity.
8. C# resilient exporters and bounded provider lifecycle.
9. Five-language hardening, runtime, collector, and packaging matrices.
10. Documentation, release automation, mutation gates, and final review.

Each task produces a buildable commit. Tests fail during the local red phase,
then pass before the task commit.

## Compatibility Policy

- Remove legacy C# environment names.
- Emit canonical snake_case local fields only.
- Reject unsupported endpoint schemes.
- Remove public capabilities that have no production implementation.
- Change pre-1.0 APIs where truthful lifecycle, receipt, or backend behavior
  requires it.
- Record changes in the 0.8 release notes.

## Acceptance Criteria

The work is complete when:

1. Every required fixture category resolves to executable evidence for five
   languages.
2. All five SDKs pass canonical output, runtime, and contract probes.
3. Core-only and OTel-enabled builds pass for every applicable language.
4. The review's critical and high-priority findings have regression tests and
   passing implementations.
5. The medium-priority correctness and hardening findings are closed or the
   shared contract has an explicit, justified applicability rule.
6. C# meets the repository's owned-code coverage and mutation standards.
7. Documentation and release automation describe the same five-language
   support model.
8. A final whole-branch review reports no unresolved critical or important
   findings.
