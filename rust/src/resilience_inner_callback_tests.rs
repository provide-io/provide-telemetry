// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

//! Callback-contract tests for `run_with_resilience_inner`.
//!
//! Mounted via `#[path]` from `resilience.rs` so the test module sits
//! beside the implementation file without making `resilience_tests.rs`
//! exceed the 500-LOC ceiling.
//!
//! `run_with_resilience_inner` is the single shared loop body behind both
//! [`run_with_resilience`] (TelemetryError-flavored) and `run_otel_resilience`
//! (OTelSdkResult-flavored). Its three error-type callbacks form the seam
//! where each variant of the loop plugs in its own error semantics. These
//! tests pin when each callback is invoked so the contract cannot drift.

use super::*;
use crate::testing::acquire_test_state_lock;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;

#[derive(Debug, Clone, PartialEq)]
enum TestErr {
    Timeout,
    CircuitOpen,
    Other,
}

#[test]
fn inner_invokes_timeout_err_when_wrapper_timeout_fires() {
    let _guard = acquire_test_state_lock();
    _reset_resilience_for_tests();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");

    let policy = ExporterPolicy {
        retries: 0,
        backoff_seconds: 0.0,
        timeout_seconds: 0.05,
        fail_open: false,
        allow_blocking_in_event_loop: false,
    };

    let te_calls = Arc::new(AtomicU32::new(0));
    let is_calls = Arc::new(AtomicU32::new(0));
    let co_calls = Arc::new(AtomicU32::new(0));

    let result = runtime.block_on(async {
        run_with_resilience_inner::<_, _, (), TestErr>(
            Signal::Logs,
            &policy,
            || async {
                tokio::time::sleep(Duration::from_millis(500)).await;
                Ok(())
            },
            {
                let c = Arc::clone(&te_calls);
                move |_dur| {
                    c.fetch_add(1, Ordering::SeqCst);
                    TestErr::Timeout
                }
            },
            {
                let c = Arc::clone(&is_calls);
                move |_e| {
                    c.fetch_add(1, Ordering::SeqCst);
                    false
                }
            },
            {
                let c = Arc::clone(&co_calls);
                move || {
                    c.fetch_add(1, Ordering::SeqCst);
                    TestErr::CircuitOpen
                }
            },
        )
        .await
    });

    assert_eq!(result, Err(TestErr::Timeout));
    assert_eq!(
        te_calls.load(Ordering::SeqCst),
        1,
        "timeout_err called exactly once on wrapper-timeout fire"
    );
    // wrapper_timeout=true short-circuits `wrapper_timeout || is_sdk_timeout(&err)`
    // — we already know it's a timeout, so the callback is intentionally skipped.
    assert_eq!(
        is_calls.load(Ordering::SeqCst),
        0,
        "is_sdk_timeout must NOT be called when wrapper_timeout is already true (short-circuit)"
    );
    assert_eq!(
        co_calls.load(Ordering::SeqCst),
        0,
        "circuit_open_err must not fire when the circuit is closed"
    );
}

#[test]
fn inner_invokes_is_sdk_timeout_for_each_operation_error() {
    let _guard = acquire_test_state_lock();
    _reset_resilience_for_tests();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");

    let policy = ExporterPolicy {
        retries: 2,
        backoff_seconds: 0.0,
        timeout_seconds: 0.0, // bypass wrapper timeout — operation Err is the only failure source
        fail_open: false,
        allow_blocking_in_event_loop: false,
    };

    let is_calls = Arc::new(AtomicU32::new(0));

    let result = runtime.block_on(async {
        run_with_resilience_inner::<_, _, (), TestErr>(
            Signal::Logs,
            &policy,
            || async { Err::<(), TestErr>(TestErr::Other) },
            |_dur| TestErr::Timeout,
            {
                let c = Arc::clone(&is_calls);
                move |_e| {
                    c.fetch_add(1, Ordering::SeqCst);
                    false
                }
            },
            || TestErr::CircuitOpen,
        )
        .await
    });

    assert_eq!(result, Err(TestErr::Other));
    // retries=2 → 3 attempts → 3 invocations of is_sdk_timeout (one per Err).
    assert_eq!(
        is_calls.load(Ordering::SeqCst),
        3,
        "is_sdk_timeout invoked once per failed attempt (retries+1 total)"
    );
}

#[test]
fn inner_invokes_circuit_open_err_when_breaker_open_and_fail_closed() {
    let _guard = acquire_test_state_lock();
    _reset_resilience_for_tests();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");

    let policy = ExporterPolicy {
        retries: 0,
        backoff_seconds: 0.0,
        timeout_seconds: 1.0, // breaker gate is consulted only when timeout != 0
        fail_open: false,
        allow_blocking_in_event_loop: false,
    };

    // Trip the breaker into open state with active cooldown.
    {
        let mut lock = circuits().lock().expect("circuit lock poisoned");
        let state = lock
            .get_mut(&Signal::Logs)
            .expect("logs state should exist");
        state.consecutive_timeouts = CIRCUIT_BREAKER_THRESHOLD;
        state.open_count = 1;
        state.tripped_at = Some(Instant::now());
    }

    let co_calls = Arc::new(AtomicU32::new(0));
    let op_calls = Arc::new(AtomicU32::new(0));

    let op_clone = Arc::clone(&op_calls);
    let result = runtime.block_on(async {
        run_with_resilience_inner::<_, _, (), TestErr>(
            Signal::Logs,
            &policy,
            move || {
                let c = Arc::clone(&op_clone);
                async move {
                    c.fetch_add(1, Ordering::SeqCst);
                    Ok(())
                }
            },
            |_dur| TestErr::Timeout,
            |_e| false,
            {
                let c = Arc::clone(&co_calls);
                move || {
                    c.fetch_add(1, Ordering::SeqCst);
                    TestErr::CircuitOpen
                }
            },
        )
        .await
    });

    assert_eq!(result, Err(TestErr::CircuitOpen));
    assert_eq!(
        co_calls.load(Ordering::SeqCst),
        1,
        "circuit_open_err invoked exactly once when breaker rejects the call"
    );
    assert_eq!(
        op_calls.load(Ordering::SeqCst),
        0,
        "operation must not run when the breaker is open"
    );
}
