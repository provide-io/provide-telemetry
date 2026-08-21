# Rust OTLP export flake — investigation record (INCONCLUSIVE)

**Status:** root cause NOT demonstrated. No production change made. No test
quarantined, skipped, retried, or given a longer sleep.

See [`2026-08-20-rust-flake-original.txt`](2026-08-20-rust-flake-original.txt)
for the preserved failure output and the reproduction statistics.

## What is established

Reproduced locally at **4 failures in 14 full-suite runs (~29%)** with
`cd rust && cargo test --all-features` at default parallelism. Always in the
`--lib` binary, always one test out of 517, never the same test twice running:

- `otel::logs::export_tests::apply_policies_alone_does_not_block_direct_log_exports`
- `otel::logs::export_tests::apply_policies_alone_does_not_block_direct_trace_exports`
- `otel::logs::export_runtime_tests::apply_policies_with_metrics_do_not_block_direct_trace_exports`

All pass in isolation and under `--test-threads=1`.

Two signatures, from the preserved health snapshots:

1. **Export failed.** `emitted_logs: 1`, `export_failures_logs: 1`,
   `export_latency_ms_logs: 0.0`. The record was emitted, the export attempt
   failed, nothing reached the collector.
2. **Export succeeded but landed elsewhere.** `emitted_traces: 1`,
   `export_failures_traces: 0`, `export_latency_ms_traces: 1.08`. Zero failures
   and a real latency reading mean a request completed — the collector the test
   was asserting against simply never saw it.

Signature 2 is the constraining one: it rules out "the export was merely slow"
and points at the request going somewhere other than the asserting collector.

## Hypothesis tested and REJECTED

**"Tests that install the process-global logger provider run without the shared
test-state lock, so they race the export tests."**

Grepping test bodies for `acquire_test_state_lock` suggested 13 unlocked tests
across `src/otel/logs_tests.rs` (7) and `src/otel/logs_shutdown_tests.rs` (6),
several with names fitting the failure signatures exactly
(`install_with_unreachable_endpoint_succeeds_under_fail_open`,
`shutdown_abandons_worker_when_deadline_exceeded`).

**This was wrong.** Those tests acquire the lock *indirectly*: the helper
`reset_logs_test_state()` (`src/otel/logs_tests.rs:37`) calls
`acquire_test_state_lock()` and returns the guard, and each of them calls it on
the first line. Adding a second `acquire_test_state_lock()` deadlocked the suite
immediately — `std::sync::Mutex` is not re-entrant — which is how the mistake
was caught. The change was reverted in full; `cargo test --lib --all-features`
is back to 517 passed, 0 failed.

Lesson for the next attempt: grepping test bodies for the lock call
under-reports serialisation. Check helpers that return a `MutexGuard`.

## Leading hypothesis, NOT yet tested

The lock serialises test *bodies*. It does not cover background work that
outlives a guard:

- `shutdown_abandons_worker_when_deadline_exceeded` deliberately abandons a
  drain worker. That worker can still be running when the next test starts.
- `MockOtlpCollector` binds an ephemeral port and drops it at end of test. The
  OS is free to hand the same port to the next test's collector.

Combined, an abandoned exporter from test A can deliver to test B's collector on
a recycled port — which is signature 2 exactly, and signature 1 whenever the old
port is closed rather than recycled. This would explain the movement between
tests, the rate, and why serial runs are clean.

## What would make this conclusive

1. Log a monotonic lifecycle generation at provider install, at each export, and
   at shutdown; assert the generation on the received request. A request whose
   generation is older than the asserting test is proof.
2. Record the bound port per `MockOtlpCollector` and assert the delivered
   request arrived on the port this test bound.
3. Build a deterministic reproducer: hold a drain worker open past the next
   install with a fault-injection hook, and bind the next collector to the same
   port. It must fail 20/20 before any fix is written.
4. Only then change code, with a temporary revert as the negative control and a
   re-measured before/after failure rate.

## Rejected as out of scope

Quarantining, `#[ignore]`, retry wrappers and longer sleeps are all forbidden by
the acceptance rule, and none were used.
