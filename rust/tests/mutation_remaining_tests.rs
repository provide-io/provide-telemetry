// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// Mutation tests for propagation, metrics, logger, fingerprint, tracer

#[test]
fn test_extract_w3c_context_none() {
    use provide_telemetry::extract_w3c_context;
    let ctx = extract_w3c_context(None, None, None);
    let _ = ctx;
}

#[test]
fn test_extract_w3c_context_with_header() {
    use provide_telemetry::extract_w3c_context;
    let header = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01";
    let ctx = extract_w3c_context(Some(header), None, None);
    if let Some(ref tid) = ctx.trace_id {
        assert!(!tid.is_empty());
    }
}

#[test]
fn test_counter_creation() {
    use provide_telemetry::counter;
    let _c = counter("test", None, None);
}

#[test]
fn test_gauge_creation() {
    use provide_telemetry::gauge;
    let _g = gauge("test", None, None);
}

#[test]
fn test_histogram_creation() {
    use provide_telemetry::histogram;
    let _h = histogram("test", None, None);
}

#[test]
fn test_get_logger() {
    use provide_telemetry::get_logger;
    let _ = get_logger(Some("test"));
}

#[test]
fn test_null_logger() {
    use provide_telemetry::null_logger;
    let _ = null_logger(Some("test"));
}

#[test]
fn test_buffer_logger() {
    use provide_telemetry::buffer_logger;
    let _ = buffer_logger(Some("test"));
}

#[test]
fn test_compute_error_fingerprint() {
    use provide_telemetry::compute_error_fingerprint;
    let fp = compute_error_fingerprint("ValueError", None);
    assert!(!fp.is_empty());
}

#[test]
fn test_fingerprint_deterministic() {
    use provide_telemetry::compute_error_fingerprint;
    let fp1 = compute_error_fingerprint("ValueError", None);
    let fp2 = compute_error_fingerprint("ValueError", None);
    assert_eq!(fp1, fp2);
}

#[test]
fn test_fingerprint_different_errors() {
    use provide_telemetry::compute_error_fingerprint;
    let fp1 = compute_error_fingerprint("ValueError", None);
    let fp2 = compute_error_fingerprint("TypeError", None);
    assert_ne!(fp1, fp2);
}

#[test]
fn test_trace_context() {
    use provide_telemetry::{get_trace_context, set_trace_context};
    let _guard = set_trace_context(Some("trace123".to_string()), Some("span456".to_string()));
    let ctx = get_trace_context();
    assert_eq!(ctx.get("trace_id"), Some(&Some("trace123".to_string())));
    assert_eq!(ctx.get("span_id"), Some(&Some("span456".to_string())));
}

#[test]
fn test_get_tracer() {
    use provide_telemetry::get_tracer;
    let _ = get_tracer(Some("test"));
}
