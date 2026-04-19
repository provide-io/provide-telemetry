// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

//! Tests for resilience.rs. Mounted via #[path] from the parent so the test
//! module sits beside the implementation file without making resilience.rs
//! exceed the 500-LOC ceiling.

use super::*;
use crate::testing::acquire_test_state_lock;

#[test]
fn resilience_test_get_circuit_state_closed_open_half_open() {
    let _guard = acquire_test_state_lock();
    _reset_resilience_for_tests();

    // Closed: default state.
    let closed = get_circuit_state(Signal::Logs).expect("state should exist");
    assert_eq!(closed.0, "closed");
    assert_eq!(closed.1, 0);
    assert_eq!(closed.2, 0.0);

    // Open: threshold reached, cooldown still active.
    {
        let mut lock = circuits().lock().expect("circuit lock poisoned");
        let state = lock
            .get_mut(&Signal::Logs)
            .expect("logs state should exist");
        state.consecutive_timeouts = CIRCUIT_BREAKER_THRESHOLD;
        state.open_count = 2;
        state.tripped_at = Some(Instant::now());
    }
    let open = get_circuit_state(Signal::Logs).expect("state should exist");
    assert_eq!(open.0, "open");
    assert_eq!(open.1, 2);
    assert!(open.2 > 0.0);

    // Half-open: cooldown elapsed, no probe in flight yet.
    {
        let mut lock = circuits().lock().expect("circuit lock poisoned");
        let state = lock
            .get_mut(&Signal::Logs)
            .expect("logs state should exist");
        state.tripped_at = Some(Instant::now() - CIRCUIT_COOLDOWN - Duration::from_secs(1));
        state.half_open_probing = false;
    }
    let half_open = get_circuit_state(Signal::Logs).expect("state should exist");
    assert_eq!(half_open.0, "half-open");
    assert_eq!(half_open.1, 2);
    assert_eq!(half_open.2, 0.0);

    // Half-open: probe explicitly in flight (half_open_probing=true).
    {
        let mut lock = circuits().lock().expect("circuit lock poisoned");
        let state = lock
            .get_mut(&Signal::Logs)
            .expect("logs state should exist");
        state.half_open_probing = true;
    }
    let probing = get_circuit_state(Signal::Logs).expect("state should exist");
    assert_eq!(probing.0, "half-open");
    assert_eq!(probing.1, 2);
    assert_eq!(probing.2, 0.0);
}

#[test]
fn resilience_test_half_open_probe_success_closes_breaker() {
    let _guard = acquire_test_state_lock();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");
    _reset_resilience_for_tests();
    set_exporter_policy(
        Signal::Logs,
        ExporterPolicy {
            retries: 0,
            backoff_seconds: 0.0,
            timeout_seconds: 0.0,
            fail_open: true,
            allow_blocking_in_event_loop: false,
        },
    )
    .expect("policy should set");

    // Trip the breaker.
    {
        let mut lock = circuits().lock().expect("circuit lock poisoned");
        let state = lock
            .get_mut(&Signal::Logs)
            .expect("logs state should exist");
        state.consecutive_timeouts = CIRCUIT_BREAKER_THRESHOLD;
        state.open_count = 1;
        // Expire the cooldown so the breaker is ready for a half-open probe.
        state.tripped_at = Some(Instant::now() - CIRCUIT_COOLDOWN - Duration::from_secs(1));
    }

    // First call after cooldown: probe is allowed through, and succeeds.
    let result = runtime.block_on(async {
        run_with_resilience(Signal::Logs, || async { Ok::<_, TelemetryError>(42u32) }).await
    });
    assert_eq!(result.unwrap(), Some(42u32));

    // After a successful probe the breaker must be closed.
    let state_after = get_circuit_state(Signal::Logs).expect("state should exist");
    assert_eq!(state_after.0, "closed");
    assert_eq!(state_after.2, 0.0);
}

#[test]
fn resilience_test_half_open_probe_failure_reopens_breaker() {
    let _guard = acquire_test_state_lock();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");
    _reset_resilience_for_tests();
    set_exporter_policy(
        Signal::Logs,
        ExporterPolicy {
            retries: 0,
            backoff_seconds: 0.0,
            // Non-zero so the circuit gate runs (timeout=0 bypasses it).
            timeout_seconds: 1.0,
            fail_open: true,
            allow_blocking_in_event_loop: false,
        },
    )
    .expect("policy should set");

    // Trip the breaker with expired cooldown — ready for half-open.
    {
        let mut lock = circuits().lock().expect("circuit lock poisoned");
        let state = lock
            .get_mut(&Signal::Logs)
            .expect("logs state should exist");
        state.consecutive_timeouts = CIRCUIT_BREAKER_THRESHOLD;
        state.open_count = 1;
        state.tripped_at = Some(Instant::now() - CIRCUIT_COOLDOWN - Duration::from_secs(1));
    }

    // The probe call fails — breaker should re-open.
    let result = runtime.block_on(async {
        run_with_resilience(Signal::Logs, || async {
            Err::<(), _>(TelemetryError::new("probe boom"))
        })
        .await
    });
    assert!(result.unwrap().is_none()); // fail_open=true

    // Breaker must be open again.
    let state_after = get_circuit_state(Signal::Logs).expect("state should exist");
    assert_eq!(state_after.0, "open");
    assert!(state_after.2 > 0.0, "cooldown must be active after re-open");
}

#[test]
fn resilience_test_concurrent_callers_during_probe_are_rejected() {
    let _guard = acquire_test_state_lock();
    _reset_resilience_for_tests();
    set_exporter_policy(
        Signal::Logs,
        ExporterPolicy {
            retries: 0,
            backoff_seconds: 0.0,
            timeout_seconds: 1.0,
            fail_open: true,
            allow_blocking_in_event_loop: false,
        },
    )
    .expect("policy should set");

    // Manually put the breaker into "probe in flight" state.
    {
        let mut lock = circuits().lock().expect("circuit lock poisoned");
        let state = lock
            .get_mut(&Signal::Logs)
            .expect("logs state should exist");
        state.consecutive_timeouts = CIRCUIT_BREAKER_THRESHOLD;
        state.open_count = 1;
        state.tripped_at = Some(Instant::now() - CIRCUIT_COOLDOWN - Duration::from_secs(1));
        state.half_open_probing = true; // Probe already in flight.
    }

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");

    // Concurrent caller should be rejected (fail-open returns Ok(None)).
    let result = runtime.block_on(async {
        run_with_resilience(Signal::Logs, || async { Ok::<_, TelemetryError>(99u32) }).await
    });
    assert_eq!(
        result.unwrap(),
        None,
        "concurrent caller during probe should be rejected as Ok(None) when fail_open"
    );
}

#[test]
fn resilience_test_concurrent_callers_during_probe_fail_closed_returns_error() {
    let _guard = acquire_test_state_lock();
    _reset_resilience_for_tests();
    set_exporter_policy(
        Signal::Logs,
        ExporterPolicy {
            retries: 0,
            backoff_seconds: 0.0,
            timeout_seconds: 1.0,
            fail_open: false,
            allow_blocking_in_event_loop: false,
        },
    )
    .expect("policy should set");

    // Probe already in flight.
    {
        let mut lock = circuits().lock().expect("circuit lock poisoned");
        let state = lock
            .get_mut(&Signal::Logs)
            .expect("logs state should exist");
        state.consecutive_timeouts = CIRCUIT_BREAKER_THRESHOLD;
        state.open_count = 1;
        state.tripped_at = Some(Instant::now() - CIRCUIT_COOLDOWN - Duration::from_secs(1));
        state.half_open_probing = true;
    }

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");

    let err = runtime
        .block_on(async {
            run_with_resilience(Signal::Logs, || async { Ok::<_, TelemetryError>(99u32) }).await
        })
        .expect_err("fail-closed + probe in flight should return Err");
    assert_eq!(err.message, "circuit breaker open");
}

#[test]
fn resilience_test_fail_closed_returns_error_and_reset_helper_restores_defaults() {
    let _guard = acquire_test_state_lock();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");
    _reset_resilience_for_tests();
    set_exporter_policy(
        Signal::Logs,
        ExporterPolicy {
            retries: 1,
            backoff_seconds: 0.0,
            timeout_seconds: 0.0,
            fail_open: false,
            allow_blocking_in_event_loop: false,
        },
    )
    .expect("policy should set");

    let err = runtime
        .block_on(async {
            run_with_resilience(Signal::Logs, || async {
                Err::<(), _>(TelemetryError::new("boom"))
            })
            .await
        })
        .expect_err("fail-closed policy should return the exporter error");
    assert_eq!(err.message, "boom");

    _reset_resilience_for_tests();
    let policy = get_exporter_policy(Signal::Logs).expect("policy should exist");
    assert_eq!(policy, ExporterPolicy::default());
    let state = get_circuit_state(Signal::Logs).expect("state should exist");
    assert_eq!(state.0, "closed");
    assert_eq!(state.1, 0);
}

#[test]
fn resilience_test_non_timeout_failures_do_not_trip_breaker() {
    // Mirrors Python (resilience.py:154), Go (resilience.go:118), TS
    // (resilience.ts:180): only timeouts count toward consecutive_timeouts;
    // any other failure resets the counter.
    let _guard = acquire_test_state_lock();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");
    _reset_resilience_for_tests();
    set_exporter_policy(
        Signal::Logs,
        ExporterPolicy {
            retries: 0,
            backoff_seconds: 0.0,
            // Non-zero so the gate runs; the operation itself returns
            // immediately so timeout never elapses — failures are
            // semantically "other," not timeouts.
            timeout_seconds: 1.0,
            fail_open: true,
            allow_blocking_in_event_loop: false,
        },
    )
    .expect("policy should set");

    // Five non-timeout failures must not trip the breaker.
    for _ in 0..5 {
        let _ = runtime.block_on(async {
            run_with_resilience(Signal::Logs, || async {
                Err::<(), _>(TelemetryError::new("not a timeout"))
            })
            .await
        });
    }
    let state = get_circuit_state(Signal::Logs).expect("state should exist");
    assert_eq!(
        state.0, "closed",
        "non-timeout failures must not trip the breaker"
    );
    assert_eq!(state.1, 0, "open_count must remain 0 with no timeouts");
}

#[test]
fn resilience_test_zero_timeout_bypasses_circuit_gate() {
    // Mirrors Python (resilience.py:177) and Go (resilience.go:170): when
    // timeout enforcement is off, the breaker has no signal to act on and
    // must not reject callers — the gate is bypassed entirely.
    let _guard = acquire_test_state_lock();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");
    _reset_resilience_for_tests();
    set_exporter_policy(
        Signal::Logs,
        ExporterPolicy {
            retries: 0,
            backoff_seconds: 0.0,
            timeout_seconds: 0.0, // disabled — bypass the breaker
            fail_open: false,
            allow_blocking_in_event_loop: false,
        },
    )
    .expect("policy should set");

    // Pre-load the breaker into the open state with active cooldown.
    {
        let mut lock = circuits().lock().expect("circuit lock poisoned");
        let state = lock
            .get_mut(&Signal::Logs)
            .expect("logs state should exist");
        state.consecutive_timeouts = CIRCUIT_BREAKER_THRESHOLD;
        state.open_count = 1;
        state.tripped_at = Some(Instant::now());
    }

    // The breaker is "open" but timeout=0 must bypass the gate, so the
    // operation actually runs and returns its result.
    let result = runtime.block_on(async {
        run_with_resilience(Signal::Logs, || async { Ok::<_, TelemetryError>(7u32) }).await
    });
    assert_eq!(
        result.unwrap(),
        Some(7u32),
        "timeout=0 must bypass the gate even when breaker is open"
    );
}
