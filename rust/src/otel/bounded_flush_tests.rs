// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Tests for the bounded drain/teardown primitives in `mod.rs`.

use super::*;

/// A drain that finished in time but failed must not report success — the
/// caller is deciding whether its records are safely out.
#[test]
fn a_failed_drain_is_reported_as_failure() {
    assert!(!bounded_flush("traces", None, || false));
}

#[test]
fn a_successful_drain_is_reported_as_success() {
    assert!(bounded_flush("traces", None, || true));
}

/// A drain still running at the deadline is abandoned and reported as a
/// failure — the records are still in the exporter's queue, which is exactly
/// what the caller is asking about. This is the path that separates flush
/// from shutdown: shutdown suppresses its library-applied deadline, flush
/// must not.
#[test]
fn a_drain_abandoned_at_the_deadline_is_reported_as_failure() {
    use crate::config::TelemetryConfig;
    use crate::testing::acquire_test_state_lock;

    let _guard = acquire_test_state_lock();
    let mut cfg = TelemetryConfig::default();
    cfg.exporter.logs_shutdown_timeout_seconds = 0.05;
    crate::runtime::set_active_config(Some(cfg));

    let (release_tx, release_rx) = std::sync::mpsc::channel();
    assert!(!bounded_flush("metrics", None, move || {
        // Outlive the library deadline, but keep a finite independent bound:
        // a comparison mutant must fail this assertion promptly rather than
        // strand the test inside a synchronous drain.
        let _ = release_rx.recv_timeout(std::time::Duration::from_millis(250));
        true
    }));
    let _ = release_tx.send(());

    crate::runtime::set_active_config(None);
}

/// With bounding switched off the drain runs inline; its result still counts.
#[test]
fn unbounded_drain_still_reports_its_result() {
    use crate::config::TelemetryConfig;
    use crate::testing::acquire_test_state_lock;

    let _guard = acquire_test_state_lock();
    let mut cfg = TelemetryConfig::default();
    cfg.exporter.logs_shutdown_timeout_seconds = 0.0;
    crate::runtime::set_active_config(Some(cfg));

    assert!(!bounded_flush("logs", None, || false));
    assert!(bounded_flush("logs", None, || true));

    crate::runtime::set_active_config(None);
}

/// `bounded_teardown` exists so the caller's deadline reaches the SDK shutdown
/// call, which takes no timeout of its own. Without it the bounded pre-flush
/// buys nothing: the teardown right behind it blocks on the 30s worker join.
#[test]
fn a_teardown_abandoned_at_the_deadline_returns_to_the_caller() {
    use crate::testing::acquire_test_state_lock;

    let _guard = acquire_test_state_lock();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    let started = std::time::Instant::now();
    bounded_teardown("traces", Some(0.05), move || {
        // Independently bounded so a comparison mutant fails this assertion
        // promptly rather than stranding the test inside a synchronous drain.
        let _ = release_rx.recv_timeout(std::time::Duration::from_millis(250));
    });
    let elapsed = started.elapsed();
    let _ = release_tx.send(());

    assert!(
        elapsed < std::time::Duration::from_millis(200),
        "teardown ran {elapsed:?} past a 0.05s deadline"
    );
}

/// A teardown that finishes inside the deadline is waited for, not abandoned:
/// the provider must actually be down before the caller moves on.
#[test]
fn a_teardown_that_finishes_in_time_is_waited_for() {
    use crate::testing::acquire_test_state_lock;

    let _guard = acquire_test_state_lock();
    let done = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let flag = std::sync::Arc::clone(&done);
    bounded_teardown("logs", Some(5.0), move || {
        flag.store(true, std::sync::atomic::Ordering::SeqCst);
    });

    assert!(done.load(std::sync::atomic::Ordering::SeqCst));
}

/// With no usable bound the teardown runs inline on the calling thread.
#[test]
fn an_unbounded_teardown_runs_inline() {
    use crate::testing::acquire_test_state_lock;

    let _guard = acquire_test_state_lock();
    let caller = std::thread::current().id();
    let (tx, rx) = std::sync::mpsc::channel();
    // 0.0 means "caller opted out of the bound"; NaN and infinity land in the
    // same branch because Duration::from_secs_f64 panics on them.
    for timeout in [0.0, f64::NAN, f64::INFINITY] {
        let tx = tx.clone();
        bounded_teardown("metrics", Some(timeout), move || {
            let _ = tx.send(std::thread::current().id());
        });
    }
    drop(tx);

    let ran_on: Vec<_> = rx.iter().collect();
    assert_eq!(ran_on, vec![caller; 3]);
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
    let mut cfg = TelemetryConfig::default();
    cfg.exporter.logs_shutdown_timeout_seconds = 0.1;
    crate::runtime::set_active_config(Some(cfg));

    let (release_tx, release_rx) = std::sync::mpsc::channel::<()>();
    let release_rx = std::sync::Arc::new(std::sync::Mutex::new(release_rx));
    let stall = || {
        let rx = std::sync::Arc::clone(&release_rx);
        move || {
            let _ = crate::_lock::lock(&rx).recv_timeout(std::time::Duration::from_millis(400));
            true
        }
    };

    let started = std::time::Instant::now();
    std::thread::scope(|scope| {
        let logs = scope.spawn(|| bounded_flush("logs", None, stall()));
        let traces = scope.spawn(|| bounded_flush("traces", None, stall()));
        let metrics = bounded_flush("metrics", None, stall());
        assert!(!logs.join().expect("logs worker"));
        assert!(!traces.join().expect("traces worker"));
        assert!(!metrics);
    });
    let elapsed = started.elapsed();
    let _ = release_tx.send(());

    assert!(
        elapsed < std::time::Duration::from_millis(300),
        "three stalled drains took {elapsed:?}, close to the sequential 0.3s"
    );
    crate::runtime::set_active_config(None);
}
