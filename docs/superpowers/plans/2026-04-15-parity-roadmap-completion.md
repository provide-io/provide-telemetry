# Parity Roadmap Completion Plan

## Goal

Complete the remaining roadmap work so parity is backed by shared behavioral
checks, cross-language runtime introspection, and contract docs that match the
real implementation.

## Execution Order

1. Strengthen the shared parity harness.
2. Use the stronger harness to fix remaining implementation drift.
3. Add runtime introspection surfaces.
4. Tighten the docs and capability signaling.
5. Run roadmap verification, then commit and push.

## Slice 1: Shared Parity Harness

- Expand `spec/run_behavioral_parity.py --check-output` to validate the full
  canonical JSON envelope:
  `service`, `env`, `version`, `logger_name`, `trace_id`, `span_id`,
  and timestamp policy.
- Add tooling tests for output normalization and comparison.
- Upgrade the shared probes so all four languages emit the same envelope via
  public APIs.
- Add shared lifecycle/config probes for:
  invalid config
  lazy initialization
  strict-schema rejection
  required-key rejection
  fail-open exporter initialization
  shutdown and re-setup

## Slice 2: Implementation Alignment

- Fix any behavior the stronger shared probes expose.
- Close the remaining Rust schema/required-key gap if it is still the outlier.
- Align any remaining shutdown/re-setup semantics surfaced by the new probes.

## Slice 3: Runtime Introspection

- Add effective-config inspection in every language.
- Add runtime-status inspection in every language with provider install state,
  fallback mode, and signal enablement.
- Add tests that validate these APIs from the public surface.

## Slice 4: Docs

- Update `docs/API.md` so lifecycle and introspection semantics match reality.
- Add a capability matrix that separates guaranteed behavior from
  experimental/feature-gated support.
- Keep language READMEs focused on syntax and setup, with shared semantics in
  the API contract docs.

## Verification

- `uv run python spec/run_behavioral_parity.py --check-output`
- `uv run python spec/validate_conformance.py`
- `cargo test --manifest-path rust/Cargo.toml`
- `cargo test --manifest-path rust/Cargo.toml --features otel`
- `go test ./...`
- `npm test`
