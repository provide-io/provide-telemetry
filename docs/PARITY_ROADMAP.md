# Polyglot Parity Roadmap

## Purpose

This roadmap turns the repo's parity goal into a concrete work plan. It is
biased toward developer experience: users should be able to move between
Python, TypeScript, Go, and Rust without relearning telemetry semantics.

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
- four idiomatic facades
- one shared parity test suite that checks behavior, not just exported symbols

## Principles

- Python remains the behavioral reference unless the contract is updated.
- Syntax may differ by language; semantics may not.
- Optional features are not parity unless they compile, run, and are tested.
- Public facades should map directly to real behavior, not to split "wrapper vs
  actual path" semantics.

## Current Focus Areas

The main ongoing focus is keeping the achieved contract from drifting:

- preserve one semantic contract across Python, TypeScript, Go, and Rust
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
- Standardize error fingerprint rules across all four languages.
- Fix any feature-gated build failures in advertised Rust `otel` paths.

Acceptance criteria:

- The same log event with the same config is accepted or dropped identically in
  all four languages.
- `cargo test --manifest-path rust/Cargo.toml`
- `cargo test --manifest-path rust/Cargo.toml --features otel`
- `uv run python spec/validate_conformance.py`
- `uv run python spec/run_behavioral_parity.py --check-output`

all pass.

### P1. Eliminate Public Facade Drift

- Make `get_logger()`, `get_tracer()`, and `get_meter()` mean the same thing in
  all four languages.
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

- Shared semantic behavior is aligned across Python, TypeScript, Go, and Rust.
- Public facades have equivalent meaning.
- Advertised optional features compile, run, and pass CI.
- Known differences are intentional, idiomatic, and documented.
- The shared parity suite checks the behavior users actually depend on.
