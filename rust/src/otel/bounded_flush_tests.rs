// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Tests for the bounded drain/teardown primitives in `bounded.rs`.

use super::bounded::{abandoned_worker_count_for_tests, bounded_flush_with, bounded_teardown_with};
use super::*;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

/// A closure that blocks until `released` flips, with an independent ceiling
/// so a broken deadline fails the test instead of hanging the suite.
fn blocked_until(released: &Arc<AtomicBool>) -> impl FnOnce() -> bool + Send + 'static {
    blocked_until_for(released, Duration::from_millis(400))
}

/// [`blocked_until`] with a caller-chosen ceiling, for tests that must keep
/// workers stranded across several assertions.
fn blocked_until_for(
    released: &Arc<AtomicBool>,
    cap: Duration,
) -> impl FnOnce() -> bool + Send + 'static {
    let released = Arc::clone(released);
    move || {
        let started = Instant::now();
        while !released.load(Ordering::Acquire) && started.elapsed() < cap {
            std::thread::sleep(Duration::from_millis(5));
        }
        true
    }
}

/// The helper itself must honor its release flag: a closure handed an
/// already-released flag returns promptly instead of sitting out its full
/// ceiling. Pins the `&&` in the wait loop — as `||` the helper ignores the
/// flag and every caller silently waits the whole cap.
#[test]
fn the_blocked_until_helper_returns_promptly_once_released() {
    let released = Arc::new(AtomicBool::new(true));
    let job = blocked_until_for(&released, Duration::from_secs(5));
    let started = Instant::now();
    assert!(job());
    assert!(
        started.elapsed() < Duration::from_secs(1),
        "a released worker must not wait out its cap"
    );
}

/// The reset helper must actually clear the shared budget. nextest runs each
/// test in its own process, so a no-op reset would never leak between tests —
/// this is the one place the reset's effect is observable.
#[test]
fn resetting_the_abandoned_worker_budget_clears_it() {
    let _guard = crate::testing::acquire_test_state_lock();
    _reset_abandoned_workers_for_tests();

    let released = Arc::new(AtomicBool::new(false));
    assert_eq!(
        bounded_flush(
            "logs",
            Some(0.01),
            blocked_until_for(&released, Duration::from_secs(3))
        ),
        DrainOutcome::TimedOut
    );
    assert_eq!(abandoned_worker_count_for_tests(), 1);

    _reset_abandoned_workers_for_tests();
    assert_eq!(
        abandoned_worker_count_for_tests(),
        0,
        "reset must clear the stranded-worker budget"
    );
    released.store(true, Ordering::Release);
}

/// A drain that finished in time but failed must not report success — the
/// caller is deciding whether its records are safely out.
#[test]
fn a_failed_drain_is_reported_as_failure() {
    let _guard = crate::testing::acquire_test_state_lock();
    assert_eq!(
        bounded_flush("traces", None, || false),
        DrainOutcome::Failed
    );
}

#[test]
fn a_successful_drain_is_reported_as_success() {
    let _guard = crate::testing::acquire_test_state_lock();
    assert_eq!(
        bounded_flush("traces", None, || true),
        DrainOutcome::Drained
    );
}

/// A drain still running at the deadline is abandoned and reported as a
/// failure — the records are still in the exporter's queue, which is exactly
/// what the caller is asking about. This is the path that separates flush
/// from shutdown: shutdown suppresses its library-applied deadline, flush
/// must not. The abandoned worker charges a budget slot and releases it on
/// its way out.
#[test]
fn a_drain_abandoned_at_the_deadline_is_reported_as_failure() {
    use crate::config::TelemetryConfig;
    use crate::testing::acquire_test_state_lock;

    let _guard = acquire_test_state_lock();
    _reset_abandoned_workers_for_tests();
    let mut cfg = TelemetryConfig::default();
    cfg.exporter.logs_shutdown_timeout_seconds = 0.05;
    crate::runtime::set_active_config(Some(cfg));

    let released = Arc::new(AtomicBool::new(false));
    assert_eq!(
        bounded_flush("metrics", None, blocked_until(&released)),
        DrainOutcome::TimedOut
    );
    assert_eq!(
        abandoned_worker_count_for_tests(),
        1,
        "an abandoned drain worker must charge a budget slot"
    );
    released.store(true, Ordering::Release);

    // The worker decrements on its way out — the budget recovers.
    let started = Instant::now();
    while abandoned_worker_count_for_tests() > 0 && started.elapsed() < Duration::from_secs(2) {
        std::thread::sleep(Duration::from_millis(5));
    }
    assert_eq!(
        abandoned_worker_count_for_tests(),
        0,
        "a stranded worker must release its slot when it finally exits"
    );

    crate::runtime::set_active_config(None);
}

/// A configured deadline of zero is a zero budget, not an opt-out: the drain
/// is started and abandoned immediately, matching Python and TypeScript.
#[test]
fn a_zero_configured_deadline_abandons_the_drain_immediately() {
    use crate::config::TelemetryConfig;
    use crate::testing::acquire_test_state_lock;

    let _guard = acquire_test_state_lock();
    _reset_abandoned_workers_for_tests();
    let mut cfg = TelemetryConfig::default();
    cfg.exporter.logs_shutdown_timeout_seconds = 0.0;
    crate::runtime::set_active_config(Some(cfg));

    let released = Arc::new(AtomicBool::new(false));
    let started = Instant::now();
    assert_eq!(
        bounded_flush("logs", None, blocked_until(&released)),
        DrainOutcome::TimedOut
    );
    assert!(
        started.elapsed() < Duration::from_millis(200),
        "a zero budget must not wait for the drain"
    );
    released.store(true, Ordering::Release);

    crate::runtime::set_active_config(None);
    _reset_abandoned_workers_for_tests();
}

/// A caller-supplied zero or negative deadline means "no budget left": abandon
/// immediately, never drain synchronously without a bound — that unbounded
/// drain is the SIGTERM hang the timeout parameter exists to prevent.
#[test]
fn a_non_positive_caller_deadline_abandons_the_drain_immediately() {
    use crate::testing::acquire_test_state_lock;

    let _guard = acquire_test_state_lock();
    _reset_abandoned_workers_for_tests();

    for deadline in [0.0, -1.0] {
        let released = Arc::new(AtomicBool::new(false));
        let started = Instant::now();
        assert_eq!(
            bounded_flush("traces", Some(deadline), blocked_until(&released)),
            DrainOutcome::TimedOut,
            "flush({deadline}) must report the drain abandoned"
        );
        assert!(
            started.elapsed() < Duration::from_millis(200),
            "flush({deadline}) must not block on the drain"
        );
        released.store(true, Ordering::Release);
    }

    _reset_abandoned_workers_for_tests();
}

/// The boundary just above zero is still a real budget: a drain that fits
/// inside it completes and reports success.
#[test]
fn a_small_positive_deadline_still_drains() {
    let _guard = crate::testing::acquire_test_state_lock();
    assert_eq!(
        bounded_flush("logs", Some(0.5), || true),
        DrainOutcome::Drained
    );
}

/// The whole point of the guard: these arguments used to panic inside
/// `shutdown_telemetry`, aborting the process instead of draining. NaN and
/// +inf mean "drain without a deadline" and run inline.
#[test]
fn bounded_flush_survives_a_non_finite_caller_timeout() {
    let _guard = crate::testing::acquire_test_state_lock();
    assert_eq!(
        bounded_flush("logs", Some(f64::NAN), || true),
        DrainOutcome::Drained
    );
    assert_eq!(
        bounded_flush("traces", Some(f64::INFINITY), || true),
        DrainOutcome::Drained
    );
    // An unbounded drain that completed and was rejected failed — nothing
    // expired, so it must never read as a timeout.
    assert_eq!(
        bounded_flush("metrics", Some(f64::MAX), || false),
        DrainOutcome::Failed
    );
}

/// At the OS thread limit the spawn fails; the drain must run inline instead
/// of panicking mid-shutdown, and still report its own result.
#[test]
fn a_failed_spawn_falls_back_to_an_inline_drain() {
    use crate::testing::acquire_test_state_lock;

    let _guard = acquire_test_state_lock();
    let failing_spawn = |_name: String, _job: Box<dyn FnOnce() + Send + 'static>| {
        Err(std::io::Error::other("thread limit reached"))
    };
    assert_eq!(
        bounded_flush_with("logs", Some(5.0), || true, failing_spawn),
        DrainOutcome::Drained
    );
    assert_eq!(
        bounded_flush_with("logs", Some(5.0), || false, failing_spawn),
        DrainOutcome::Failed
    );
}

/// The teardown counterpart: a failed spawn tears down inline, on the calling
/// thread, rather than panicking or skipping the teardown.
#[test]
fn a_failed_teardown_spawn_tears_down_inline() {
    use crate::testing::acquire_test_state_lock;

    let _guard = acquire_test_state_lock();
    let caller = std::thread::current().id();
    let (tx, rx) = std::sync::mpsc::channel();
    bounded_teardown_with(
        "logs",
        Some(5.0),
        move || {
            let _ = tx.send(std::thread::current().id());
        },
        |_name, _job| Err(std::io::Error::other("thread limit reached")),
    );
    assert_eq!(rx.try_recv(), Ok(caller));
}

/// Past the stranded-worker budget, flush declines to start another worker —
/// the drain is reported failed and the job never runs — while teardown, the
/// last chance to get records out, still proceeds.
#[test]
fn a_saturated_budget_declines_flush_but_never_teardown() {
    use crate::testing::acquire_test_state_lock;

    let _guard = acquire_test_state_lock();
    _reset_abandoned_workers_for_tests();

    // Strand workers up to the cap.
    let released = Arc::new(AtomicBool::new(false));
    for n in 0..8 {
        assert_eq!(
            bounded_flush(
                "logs",
                Some(0.01),
                blocked_until_for(&released, Duration::from_secs(3))
            ),
            DrainOutcome::TimedOut,
            "stranding flush {n} must report an abandoned drain"
        );
    }
    assert_eq!(abandoned_worker_count_for_tests(), 8);

    // The ninth flush declines: the drain never ran, and the outcome is
    // TimedOut — the records are hostage to the earlier deadline expiries
    // that saturated the budget, matching what Python's `_drain_signal`
    // reports for a declined drain.
    let ran = Arc::new(AtomicBool::new(false));
    let ran_flag = Arc::clone(&ran);
    assert_eq!(
        bounded_flush("logs", Some(5.0), move || {
            ran_flag.store(true, Ordering::Release);
            true
        }),
        DrainOutcome::TimedOut
    );
    assert!(
        !ran.load(Ordering::Acquire),
        "a declined flush must not strand another worker"
    );

    // Teardown never declines — it still runs, and is waited for.
    let done = Arc::new(AtomicBool::new(false));
    let done_flag = Arc::clone(&done);
    bounded_teardown("logs", Some(5.0), move || {
        done_flag.store(true, Ordering::Release);
    });
    assert!(
        done.load(Ordering::Acquire),
        "teardown must proceed even with the budget saturated"
    );

    released.store(true, Ordering::Release);
    _reset_abandoned_workers_for_tests();
}

/// `bounded_teardown` exists so the caller's deadline reaches the SDK shutdown
/// call, which takes no timeout of its own. Without it the bounded pre-flush
/// buys nothing: the teardown right behind it blocks on the 30s worker join.
#[test]
fn a_teardown_abandoned_at_the_deadline_returns_to_the_caller() {
    use crate::testing::acquire_test_state_lock;

    let _guard = acquire_test_state_lock();
    _reset_abandoned_workers_for_tests();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    let started = Instant::now();
    bounded_teardown("traces", Some(0.05), move || {
        // Independently bounded so a comparison mutant fails this assertion
        // promptly rather than stranding the test inside a synchronous drain.
        let _ = release_rx.recv_timeout(Duration::from_millis(250));
    });
    let elapsed = started.elapsed();
    let _ = release_tx.send(());

    assert!(
        elapsed < Duration::from_millis(200),
        "teardown ran {elapsed:?} past a 0.05s deadline"
    );
    assert_eq!(
        abandoned_worker_count_for_tests(),
        1,
        "an abandoned teardown worker still charges the shared budget"
    );
    _reset_abandoned_workers_for_tests();
}

/// A teardown that finishes inside the deadline is waited for, not abandoned:
/// the provider must actually be down before the caller moves on.
#[test]
fn a_teardown_that_finishes_in_time_is_waited_for() {
    use crate::testing::acquire_test_state_lock;

    let _guard = acquire_test_state_lock();
    let done = Arc::new(AtomicBool::new(false));
    let flag = Arc::clone(&done);
    bounded_teardown("logs", Some(5.0), move || {
        flag.store(true, Ordering::SeqCst);
    });

    assert!(done.load(Ordering::SeqCst));
}

/// With no usable bound (NaN, +inf) the teardown runs inline on the calling
/// thread; a zero deadline is a zero budget and returns without waiting.
#[test]
fn an_unbounded_teardown_runs_inline_and_a_zero_budget_does_not_wait() {
    use crate::testing::acquire_test_state_lock;

    let _guard = acquire_test_state_lock();
    _reset_abandoned_workers_for_tests();
    let caller = std::thread::current().id();
    let (tx, rx) = std::sync::mpsc::channel();
    for timeout in [f64::NAN, f64::INFINITY] {
        let tx = tx.clone();
        bounded_teardown("metrics", Some(timeout), move || {
            let _ = tx.send(std::thread::current().id());
        });
    }
    drop(tx);
    let ran_on: Vec<_> = rx.iter().collect();
    assert_eq!(ran_on, vec![caller; 2]);

    let started = Instant::now();
    let released = Arc::new(AtomicBool::new(false));
    let blocked = blocked_until(&released);
    bounded_teardown("metrics", Some(0.0), move || {
        let _ = blocked();
    });
    assert!(
        started.elapsed() < Duration::from_millis(200),
        "a zero-budget teardown must not wait for the worker"
    );
    released.store(true, Ordering::Release);
    _reset_abandoned_workers_for_tests();
}

/// The overlap `flush_otel_by_signal` and `shutdown_otel` rely on: run together
/// the drains share one budget instead of taking it in turn. Sequentially three
/// stalled exporters cost three deadlines, so a SIGTERM handler that passed the
/// 5s it had left would wait 15s and be SIGKILLed with records still queued.
#[test]
fn stalled_drains_run_together_share_one_deadline() {
    use crate::config::TelemetryConfig;
    use crate::testing::acquire_test_state_lock;

    let _guard = acquire_test_state_lock();
    _reset_abandoned_workers_for_tests();
    let mut cfg = TelemetryConfig::default();
    cfg.exporter.logs_shutdown_timeout_seconds = 0.1;
    crate::runtime::set_active_config(Some(cfg));

    let released = Arc::new(AtomicBool::new(false));
    let started = Instant::now();
    std::thread::scope(|scope| {
        let logs = scope.spawn(|| bounded_flush("logs", None, blocked_until(&released)));
        let traces = scope.spawn(|| bounded_flush("traces", None, blocked_until(&released)));
        let metrics = bounded_flush("metrics", None, blocked_until(&released));
        assert_eq!(logs.join().expect("logs worker"), DrainOutcome::TimedOut);
        assert_eq!(
            traces.join().expect("traces worker"),
            DrainOutcome::TimedOut
        );
        assert_eq!(metrics, DrainOutcome::TimedOut);
    });
    let elapsed = started.elapsed();
    released.store(true, Ordering::Release);

    assert!(
        elapsed < Duration::from_millis(300),
        "three stalled drains took {elapsed:?}, close to the sequential 0.3s"
    );
    crate::runtime::set_active_config(None);
    _reset_abandoned_workers_for_tests();
}

/// The scoped-spawn fallback: a handle joins normally, a failed spawn runs the
/// drain inline. This is the path that keeps `flush_otel_by_signal` and
/// `shutdown_otel` from panicking at the OS thread limit.
#[test]
fn join_or_inline_joins_a_worker_and_falls_back_inline_on_spawn_failure() {
    std::thread::scope(|scope| {
        let spawned = std::thread::Builder::new()
            .name("provide-test-drain".to_string())
            .spawn_scoped(scope, || 7);
        assert_eq!(super::bounded::join_or_inline(spawned, || 0), 7);

        let failed: std::io::Result<std::thread::ScopedJoinHandle<'_, i32>> =
            Err(std::io::Error::other("thread limit reached"));
        assert_eq!(super::bounded::join_or_inline(failed, || 42), 42);
    });
}
