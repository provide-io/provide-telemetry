# Quality Gap-to-Closure Checklist

This checklist records the evidence required before the `0.7.0` quality work is
called complete. Coverage, parameterization, and mutation testing are separate
gates: line coverage alone is not treated as evidence that behavior is useful.

## 1. Meaningful 100% coverage

- [x] Python's default suite enforces 100% statement and branch coverage through
  `scripts/run_pytest_gate.py`.
- [x] TypeScript enforces 100% statements, branches, functions, and lines with
  `npm run test:coverage`.
- [x] Go enforces 100% coverage independently for the root, `logger`, and `otel`
  packages.
- [x] Rust enforces zero uncovered executable lines and 100% covered functions
  with `cargo llvm-cov`.
- [x] Public `TelemetryRuntime` lifecycle behavior is exercised directly:
  construction, startup success and degradation, immutable snapshots,
  provider-aware flush results, successful and rejected reconfiguration,
  environment reload, shutdown, and error structure.
- [x] Coverage includes error, fallback, governance, nested-security, context,
  metrics, lifecycle, and resilience paths rather than excluding them as
  optional code.

Coverage is a reachability gate. The mutation and behavioral-fixture gates below
are what prevent assertion-free execution from satisfying the quality policy.

## 2. Parameterized cross-language behavioral evidence

- [x] The executable contract defines 24 mandatory fixture categories.
- [x] `spec/fixture_test_ids.yaml` maps every category to a concrete test ID in
  Python, TypeScript, Go, and Rust: 96 mappings in total.
- [x] `spec/check_fixture_test_ids.py` rejects missing languages, categories,
  duplicate IDs, and references that cannot be found in the relevant test
  corpus.
- [x] `spec/check_fixture_coverage.py --strict` rejects a behavioral category
  that is not exercised by every language.
- [x] `spec/run_behavioral_parity.py` executes the shared literal JSON,
  configuration, runtime, and contract-DSL fixtures against every language.
- [x] CI runs fixture coverage, fixture-ID validation, conformance validation,
  and behavioral parity as blocking jobs.

The fixture-ID manifest is an evidence index, not a substitute for execution:
the strict coverage and parity runners must also pass.

## 3. Mutation testing

- [x] Python rejects timeouts and enforces a 95% mutation score.
- [x] TypeScript enforces a 95% core mutation score and an 80% OTLP transport
  score.
- [x] Go requires both 100% mutation efficacy and 100% mutant coverage for the
  root, `logger`, and `otel` packages.
- [x] Rust requires every viable mutant to be caught under all features. The
  final tree enumerates 1,156 raw candidates; seven narrowly documented
  equivalent exclusions leave 1,149 gate candidates. Exact-name ledger
  reconciliation leaves zero current candidates unaccounted for, and the final
  affected-file rerun caught all 28 re-enumerated candidates with zero misses
  or timeouts.
- [x] Rust mutation CI uses pinned `cargo-mutants` and `cargo-nextest` versions,
  runs all features, partitions the complete inventory into eight disjoint
  blocking shards, and runs whenever Rust implementation, tests, or mutation
  policy change.
- [x] Mutation-tool configuration and CI thresholds have repository tests so a
  later workflow edit cannot silently weaken the policy.

## Closure rule

All boxes above must be checked, the ordinary language quality suites must still
pass after the last mutation-driven change, and `git diff --check` must be clean.
No claim of full specification-v2 feature completion follows from this
checklist; it covers the three requested quality controls only.
