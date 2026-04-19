# Developer Experience Rubric

## Purpose

This rubric defines what "delightful and consistent" means for a polyglot telemetry library. It is intended to guide design reviews, release readiness, and parity work across Python, TypeScript, Go, and Rust.

The goal is not identical syntax. The goal is identical user intent and predictable observable behavior, expressed through idiomatic APIs in each language.

## North Star

- One shared semantic contract across all languages.
- One obvious happy path for local development and one for production setup.
- Language-specific APIs stay familiar and idiomatic.
- Idiomatic differences never silently change behavior.
- Shared guarantees are explicit, testable, and documented.

## Scoring

Score each dimension on a 0-2 scale:

- `0` — inconsistent, surprising, or undocumented
- `1` — mostly acceptable, but with gaps or caveats
- `2` — consistent, predictable, and well documented

Maximum score: `16`

## Dimensions

### 1. Happy Path Clarity

- A new user can emit a log, trace, and metric in under five minutes.
- Each language has one obvious "local dev" path and one obvious "production" path.
- The first example in each language matches the same conceptual flow.

### 2. Semantic Consistency

- The same intent yields the same observable behavior across all languages.
- Config precedence is identical.
- Level filtering, consent, sampling, schema, PII, backpressure, and fail-open behavior are identical.
- Lazy initialization behaves the same as explicit setup for common cases.

### 3. Idiomatic Feel

- Python feels Pythonic.
- TypeScript feels Node/browser-native.
- Go feels explicit and `context.Context`-oriented.
- Rust feels typed, RAII-based, and feature-gated where appropriate.
- Language-specific affordances are additive rather than semantic forks.

### 4. Safe Defaults

- Zero-config local mode is useful and predictable.
- Invalid configuration fails clearly and consistently.
- Default behavior avoids data leaks, invalid envelopes, and surprising drops.

### 5. Runtime Inspectability

- Users can inspect the active config, runtime mode, provider installation state, and health snapshot.
- Drop reasons and fallback states are observable enough to debug real issues.

### 6. Testable Behavior

- Shared parity tests cover meaningful behavior, not just symbol export.
- Language-specific tests verify idiomatic facades without weakening the shared contract.
- Optional features are tested wherever docs and CI claim support.

### 7. Documentation Coherence

- There is one contract doc for shared guarantees.
- Language READMEs focus on syntax, setup, caveats, and examples.
- Known gaps and intentional differences are documented explicitly.

### 8. Operational Reliability

- Setup, shutdown, and re-setup cycles are safe.
- Fallback and fail-open behavior are deterministic.
- Public APIs do not split into "real" and "stub" behavior without being obvious.

## Release Gate Questions

Use these questions during review:

1. Can a user predict what happens without reading implementation code?
1. Does the same config produce the same outcome in all four languages?
1. Are the common paths easy, and are the advanced paths discoverable?
1. Are invalid states surfaced clearly instead of silently degraded?
1. Are all advertised feature combinations exercised in CI?
1. Are known differences documented as intentional and idiomatic?

## Classification Model

Every cross-language behavior should fall into exactly one category:

- `Core guaranteed behavior` Behavior that must match across all languages.
- `Idiomatic language difference` Syntax or shape differences that preserve the same semantics.
- `Known gap` Current divergence that is not yet resolved and must be tracked.

If a behavior cannot be classified cleanly, the contract is underspecified.

## Recommended Usage

- Use this rubric in architecture reviews.
- Use it in release readiness checks.
- Use it when evaluating whether a language implementation is at parity.
- Use it to distinguish acceptable idiomatic differences from parity bugs.
