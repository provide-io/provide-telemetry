// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use crate::backpressure::_reset_backpressure_for_tests;
use crate::cardinality::clear_cardinality_limits;
#[cfg(feature = "governance")]
use crate::classification::clear_classification_rules;
#[cfg(feature = "governance")]
use crate::consent::reset_consent_for_tests;
use crate::context::{reset_context_for_tests, reset_trace_context_for_tests};
use crate::health::_reset_health_for_tests;
use crate::metrics::reset_metrics_for_tests;
use crate::otel::_reset_otel_for_tests;
use crate::pii::replace_pii_rules;
#[cfg(feature = "governance")]
use crate::receipts::reset_receipts_for_tests;
use crate::resilience::_reset_resilience_for_tests;
use crate::sampling::_reset_sampling_for_tests;
use crate::schema::_reset_strict_schema_for_tests;
use crate::setup::shutdown_telemetry;
use crate::slo::reset_slo_for_tests;
use crate::tracer::set_trace_context;
use std::sync::{Mutex, MutexGuard, OnceLock};

static TEST_STATE_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn test_state_lock() -> &'static Mutex<()> {
    TEST_STATE_LOCK.get_or_init(|| Mutex::new(()))
}

/// Serialize tests that mutate process-global telemetry state.
pub fn acquire_test_state_lock() -> MutexGuard<'static, ()> {
    test_state_lock().lock().expect("test state lock poisoned")
}

/// Reset all telemetry state to keep tests isolated.
pub fn reset_telemetry_state() {
    let _ = shutdown_telemetry();
    _reset_otel_for_tests();
    _reset_health_for_tests();
    _reset_backpressure_for_tests();
    _reset_sampling_for_tests();
    _reset_resilience_for_tests();
    reset_metrics_for_tests();
    #[cfg(feature = "governance")]
    reset_receipts_for_tests();
    #[cfg(feature = "governance")]
    reset_consent_for_tests();
    reset_slo_for_tests();
    clear_cardinality_limits();
    #[cfg(feature = "governance")]
    clear_classification_rules();
    replace_pii_rules(Vec::new());
    _reset_strict_schema_for_tests();
    reset_context_for_tests();
}

/// Clear manual trace context to prevent cross-test leakage.
pub fn reset_trace_context() {
    reset_trace_context_for_tests();
    drop(set_trace_context(None, None));
}
