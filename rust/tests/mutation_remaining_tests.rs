// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// Mutation tests for remaining modules: propagation, metrics, logger, fingerprint, tracer

// ============================================================================
// PROPAGATION TESTS
// ============================================================================

#[test]
fn test_extract_w3c_context_with_valid_header() {
    use provide_telemetry::extract_w3c_context;

    let valid_header = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01";
    let ctx = extract_w3c_context(Some(valid_header), None, None);

    // Context should be created successfully
    assert!(!ctx.trace_id.is_empty());
}

#[test]
fn test_extract_w3c_context_with_none() {
    use provide_telemetry::extract_w3c_context;

    let ctx = extract_w3c_context(None, None, None);
    // Should handle None gracefully
    let _ = ctx;
}

// ============================================================================
// METRICS TESTS
// ============================================================================

#[test]
fn test_counter_creation() {
    use provide_telemetry::counter;

    let _c = counter("test_counter", []);
    // Counter should be created without panicking
}

#[test]
fn test_gauge_creation() {
    use provide_telemetry::gauge;

    let _g = gauge("test_gauge", 0.0, []);
    // Gauge should be created without panicking
}

#[test]
fn test_histogram_creation() {
    use provide_telemetry::histogram;

    let _h = histogram("test_histogram", []);
    // Histogram should be created without panicking
}

// ============================================================================
// LOGGER TESTS
// ============================================================================

#[test]
fn test_get_logger() {
    use provide_telemetry::get_logger;

    let _ = get_logger("test_component");
    // Logger should be retrieved without panicking
}

#[test]
fn test_null_logger() {
    use provide_telemetry::null_logger;

    let _ = null_logger();
    // Null logger should be created without panicking
}

#[test]
fn test_buffer_logger() {
    use provide_telemetry::buffer_logger;
    use std::io::Cursor;

    let buffer = Cursor::new(Vec::new());
    let _ = buffer_logger(buffer);
    // Buffer logger should be created without panicking
}

// ============================================================================
// FINGERPRINT TESTS
// ============================================================================

#[test]
fn test_compute_error_fingerprint() {
    use provide_telemetry::compute_error_fingerprint;

    let fp = compute_error_fingerprint("ValueError", &[]);
    // Fingerprint should be generated consistently
    assert!(!fp.is_empty());
}

#[test]
fn test_fingerprint_deterministic() {
    use provide_telemetry::compute_error_fingerprint;

    let fp1 = compute_error_fingerprint("ValueError", &[]);
    let fp2 = compute_error_fingerprint("ValueError", &[]);
    assert_eq!(fp1, fp2, "fingerprint should be deterministic");
}

#[test]
fn test_fingerprint_different_for_different_errors() {
    use provide_telemetry::compute_error_fingerprint;

    let fp1 = compute_error_fingerprint("ValueError", &[]);
    let fp2 = compute_error_fingerprint("TypeError", &[]);
    assert_ne!(fp1, fp2, "different errors should have different fingerprints");
}

// ============================================================================
// TRACER TESTS
// ============================================================================

#[test]
fn test_get_trace_context() {
    use provide_telemetry::get_trace_context;

    let (trace_id, span_id) = get_trace_context();
    // Should return valid context
    let _ = (trace_id, span_id);
}

#[test]
fn test_set_and_get_trace_context() {
    use provide_telemetry::{set_trace_context, get_trace_context};

    set_trace_context("test_trace_123", "test_span_456");
    let (trace_id, span_id) = get_trace_context();

    assert_eq!(trace_id, "test_trace_123");
    assert_eq!(span_id, "test_span_456");
}

#[test]
fn test_get_tracer() {
    use provide_telemetry::get_tracer;

    let _ = get_tracer("test_component");
    // Tracer should be retrieved without panicking
}
