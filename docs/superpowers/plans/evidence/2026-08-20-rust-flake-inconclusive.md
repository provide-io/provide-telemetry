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

All pass when run in isolation. They were also believed to pass under
`--test-threads=1` — see the serial reproduction below, which disproves that.

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

## Second reproduction: it happens SERIALLY too

On 2026-08-20, during the coverage run, the same test failed under
`RUST_TEST_THREADS=1`:

```
otel::logs::export_tests::apply_policies_alone_does_not_block_direct_trace_exports
src/otel/logs_export_tests.rs:354
expected /v1/traces export, saw []
emitted_traces: 1, export_failures_traces: 0, export_latency_ms_traces: 1.17
```

Signature 2 again — a completed export the asserting collector never saw — but
with **no concurrent test bodies at all**. This kills the whole family of
"two tests ran at once" explanations, including the rejected one above, and
leaves only mechanisms where work outlives the test that started it.

The same run surfaced a second, independent flaky test in the same area:

```
otel::bounded_flush_tests::a_teardown_abandoned_at_the_deadline_returns_to_the_caller
src/otel/bounded_flush_tests.rs:358
provide_telemetry: traces shutdown exceeded 0.050s deadline; abandoning background flush
assertion `left == right` failed: an abandoned teardown worker still charges the shared budget
  left: 0, right: 1
```

That test releases the abandoned worker (`release_tx.send(())`) *before* it
asserts the abandoned-worker count, so a worker finishing in that window
decrements the count back to zero and the assertion reads 0. It is a narrower
and far more tractable race than the export flake, it lives in the same
abandoned-worker machinery, and it is worth attacking first: a deterministic
reproducer there is straightforward — hold the worker until after the
assertion.

## Leading hypothesis, NOT yet tested

The lock serialises test *bodies*. It does not cover background work that
outlives a guard:

- `shutdown_abandons_worker_when_deadline_exceeded` deliberately abandons a
  drain worker. That worker can still be running when the next test starts.
- `MockOtlpCollector` binds an ephemeral port and drops it at end of test. The
  OS is free to hand the same port to the next test's collector.

Combined, an abandoned exporter from test A can deliver to test B's collector on
a recycled port — which is signature 2 exactly, and signature 1 whenever the old
port is closed rather than recycled. This explains the movement between tests,
the rate, and — crucially — why it still happens serially: an abandoned worker
does not care how many test threads there are.

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
