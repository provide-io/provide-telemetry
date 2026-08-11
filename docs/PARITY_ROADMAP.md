# Polyglot Parity Roadmap

## Purpose

This roadmap turns the repo's parity goal into a concrete work plan. It is
biased toward developer experience: users should be able to move between
Python, TypeScript, Go, Rust, and C# without relearning telemetry semantics.

## Status

As of 2026-04-15, the roadmap work below is implemented in the repo and backed
by the shared behavioral parity suite. The parity runner now checks canonical
log-envelope fields plus shared lifecycle/config cases for lazy initialization,
strict-schema rejection, required-key rejection, invalid config, fail-open
exporter initialization, and shutdown+re-setup.

Treat the remaining sections as the maintained parity contract and regression
criteria rather than an untriaged backlog.

## Target Outcome

The target is:

- one semantic contract
- five idiomatic facades
- one shared parity test suite that checks behavior, not just exported symbols

## Principles

- Python remains the behavioral reference unless the contract is updated.
- Syntax may differ by language; semantics may not.
- Optional features are not parity unless they compile, run, and are tested.
- Public facades should map directly to real behavior, not to split "wrapper vs
  actual path" semantics.

## Current Focus Areas

The main ongoing focus is keeping the achieved contract from drifting:

- preserve one semantic contract across Python, TypeScript, Go, Rust, and C#
- keep optional OTLP paths honest about dependency and feature-gate boundaries
- extend shared parity probes whenever new user-visible behavior is added
- keep docs aligned with what the runtime-status and parity suites actually
  guarantee

## Workstreams

### P0. Fix Semantic Breaks

- Ensure Rust direct `Logger` calls respect configured log level.
- Align Rust strict-schema behavior with the cross-language contract.
- Parse and enforce Rust `required_keys` the same way as the other languages.
- Make Rust hardening UTF-8 safe when truncating string values.
- Standardize error fingerprint rules across all five languages.
- Fix any feature-gated build failures in advertised Rust `otel` paths.

Acceptance criteria:

- The same log event with the same config is accepted or dropped identically in
  all five languages.
- `cargo test --manifest-path rust/Cargo.toml`
- `cargo test --manifest-path rust/Cargo.toml --features otel`
- `uv run python spec/validate_conformance.py`
- `uv run python spec/run_behavioral_parity.py --check-output`

all pass.

### P0b. Close Rust and C# Facade Gaps

Known gaps where a language lacks a feature the others already ship. These are
tracked here instead of under P1 because they are missing surface area, not
drift between existing surfaces.

- **ASGI/HTTP request-lifecycle middleware (P1 priority).** Only Python ships
  one: `provide.telemetry.asgi.TelemetryMiddleware` binds request/session
  context, extracts W3C traceparent/tracestate and baggage, and clears context
  on response. Every other runtime has the building blocks but no wrapper —
  TypeScript (`extractW3CContext()` + context helpers, see
  `typescript/README.md`), Go (`ExtractW3CContext` + explicit contexts, see
  `go/README.md`), Rust (`extract_w3c_context()` and `bind_context()` /
  `clear_context()`), and C# (`ExtractW3CContext()`, `Context.PushContext()`,
  `Context.PushTraceContext()`). Ship an Express/Koa-style middleware for
  TypeScript, an `httpmw` package for Go, a `tower::Layer` crate module for
  Rust, and an ASP.NET Core middleware / `IApplicationBuilder` extension for
  C#.
- **Pretty log renderer (P2 priority).** `PROVIDE_LOG_FORMAT=pretty` produces an
  ANSI-coloured renderer in Python, TypeScript, Go and Rust — Rust's shipped as
  `rust/src/logger/pretty.rs`, closing the gap this bullet originally
  tracked. C# is now the outlier: `Logger.Render` treats `pretty` as
  quoted key=value text with no ANSI, no TTY check and no
  `PROVIDE_LOG_PRETTY_FIELDS` support. Its unread
  `LoggingConfig.PrettyKeyColor` / `PrettyValueColor` / `PrettyFields`
  properties have been dropped rather than wired up, because the contract does
  not grant C# those variables — `spec/telemetry-api.yaml` scopes
  `PROVIDE_LOG_PRETTY_*` to the other four. Implementing the renderer remains
  open; the misleading config surface does not.
- **Metrics fallback export on shutdown (P3 priority).** When the `otel`
  feature is off, Rust accumulates counter/gauge/histogram state in-process
  and drops it on shutdown; C#'s core-only package does the same. Python
  flushes a JSON snapshot of the fallback state to stderr during
  `shutdown_telemetry()` (`src/provide/telemetry/metrics/fallback.py`). Decide
  whether Rust, Go, TypeScript, and C# should adopt the same stderr-JSON
  fallback or whether this becomes a documented Python-only convenience.

Acceptance criteria:

- A Rust axum service can install a single `TelemetryLayer`, and an ASP.NET Core
  application a single middleware, and each observes the same
  request-lifecycle telemetry as the Python ASGI middleware.
- `PROVIDE_LOG_FORMAT=pretty` produces ANSI-coloured output in C#, or the
  unread pretty-colour properties are removed from the C# config.
- In-process metric state is either exported or documented as a known drop on
  shutdown across all five languages.

### P1. Eliminate Public Facade Drift

- Make `get_logger()`, `get_tracer()`, and `get_meter()` mean the same thing in
  all five languages.
- Ensure lazy-init behavior is consistent with explicit setup for the common
  path.
- Decide whether test helpers such as buffer loggers are full telemetry-path
  utilities or intentionally lighter-weight fixtures, and document them
  accordingly.
- Align shutdown and re-setup lifecycle semantics across all implementations.

Acceptance criteria:

- Public facade docs no longer need language-specific caveats to explain basic
  semantic differences.
- A shutdown followed by setup produces the same runtime mode and provider state
  in all languages.

### P2. Expand Parity Verification

- Extend the parity runner to assert more than `message` and `level`.
- Verify canonical log envelope fields including `service`, `env`, `version`,
  trace IDs, span IDs, and timestamp policy.
- Add shared fixture cases for:
  invalid config
  lazy initialization
  strict-schema rejection
  required-key rejection
  fail-open exporter initialization
  shutdown and re-setup
- Keep conformance tests for exported symbols, but treat them as necessary and
  not sufficient.

Acceptance criteria:

- A passing parity run provides high confidence that end users will observe the
  same behavior across languages.

### P3. Improve Runtime Ergonomics

- Add effective-config inspection in every language.
- Add runtime-status inspection for provider install state, fallback mode, and
  signal enablement.
- Add clearer health and drop-reason visibility for debugging.
- Provide one minimal example and one production OTLP example in each language.

Acceptance criteria:

- A user can answer "what config am I actually running with?" and "why was this
  telemetry dropped?" without reading implementation code.

### P4. Tighten Documentation and Positioning

- Treat `docs/API.md` as the shared semantic contract, not just an index of
  exports.
- Keep language READMEs focused on syntax, setup, and caveats.
- Document every known gap as either:
  `core guaranteed behavior`
  `idiomatic language difference`
  `known gap`
- Add a capability matrix that separates guaranteed features from experimental
  or feature-gated ones.

Acceptance criteria:

- The docs make it easy to tell what is guaranteed, what is idiomatic, and what
  is still in progress.

## Recommended Execution Order

1. Fix semantic breaks in the implementations.
2. Expand the parity suite so regressions become visible.
3. Remove facade drift and lifecycle inconsistencies.
4. Add runtime introspection and better debugging ergonomics.
5. Tighten the contract and capability docs.

## Definition of Done

Parity should only be claimed when all of the following are true:

- Shared semantic behavior is aligned across Python, TypeScript, Go, Rust, and C#.
- Public facades have equivalent meaning.
- Advertised optional features compile, run, and pass CI.
- Known differences are intentional, idiomatic, and documented.
- The shared parity suite checks the behavior users actually depend on.
