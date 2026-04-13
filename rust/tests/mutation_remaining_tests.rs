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

// --- normalize_frames coverage ---
// Kills: replace normalize_frames with vec![] / vec![String::new()] / vec!["xyzzy".into()]
// All three stubs make every stack produce the same fingerprint, which these tests detect.

#[test]
fn fingerprint_with_stack_differs_from_no_stack() {
    use provide_telemetry::compute_error_fingerprint;
    // Kills vec![] — stub collapses stack to nothing, giving same hash as None.
    let without = compute_error_fingerprint("ValueError", None);
    let with_stack = compute_error_fingerprint("ValueError", Some("module_a.py\nmodule_b.py"));
    assert_ne!(
        with_stack, without,
        "a non-empty stack must change the fingerprint"
    );
}

#[test]
fn fingerprint_different_stacks_produce_different_hashes() {
    use provide_telemetry::compute_error_fingerprint;
    // Kills vec![], vec![String::new()], vec!["xyzzy".into()] — each stub returns the
    // same value for every input, so two distinct stacks would hash identically.
    let fp1 = compute_error_fingerprint("ValueError", Some("module_a.py"));
    let fp2 = compute_error_fingerprint("ValueError", Some("module_b.py"));
    assert_ne!(
        fp1, fp2,
        "different stack frames must produce different fingerprints"
    );
}

#[test]
fn fingerprint_stack_normalizes_path_separators() {
    use provide_telemetry::compute_error_fingerprint;
    // normalize_frames replaces '\' with '/' and takes the last path component.
    let unix = compute_error_fingerprint("ValueError", Some("src/app/module.py"));
    let windows = compute_error_fingerprint("ValueError", Some("src\\app\\module.py"));
    assert_eq!(
        unix, windows,
        "path separators must be normalised to the same last component"
    );
}

#[test]
fn fingerprint_stack_is_deterministic_with_frames() {
    use provide_telemetry::compute_error_fingerprint;
    let fp1 = compute_error_fingerprint("ValueError", Some("  app.py\n  utils.py\n  core.py"));
    let fp2 = compute_error_fingerprint("ValueError", Some("  app.py\n  utils.py\n  core.py"));
    assert_eq!(
        fp1, fp2,
        "same stack must always produce the same fingerprint"
    );
}

#[test]
fn otel_installed_for_tests_returns_false_without_otel_feature() {
    // Kills: replace otel_installed_for_tests -> bool with true
    // Without the "otel" feature, the OTLP provider is never built and
    // OTEL_INSTALLED is never set to true. This asserts the expected state.
    assert!(
        !provide_telemetry::otel_installed_for_tests(),
        "otel must not be marked as installed when built without the otel feature"
    );
}

// --- ClassificationPolicy get/set (governance feature only) ---

#[cfg(feature = "governance")]
#[test]
fn classification_policy_default_values() {
    // Kills: replace default() with all-empty strings or wrong values.
    let policy = provide_telemetry::ClassificationPolicy::default();
    assert_eq!(policy.public, "pass");
    assert_eq!(policy.internal, "pass");
    assert_eq!(policy.pii, "redact");
    assert_eq!(policy.phi, "drop");
    assert_eq!(policy.pci, "hash");
    assert_eq!(policy.secret, "drop");
}

#[cfg(feature = "governance")]
#[test]
fn classification_policy_set_and_get_roundtrip() {
    // Kills: replace set_classification_policy with () or get with default.
    let custom = provide_telemetry::ClassificationPolicy {
        public: "pass".to_string(),
        internal: "redact".to_string(),
        pii: "drop".to_string(),
        phi: "drop".to_string(),
        pci: "drop".to_string(),
        secret: "drop".to_string(), // pragma: allowlist secret
    };
    provide_telemetry::set_classification_policy(custom.clone());
    let got = provide_telemetry::get_classification_policy();
    assert_eq!(got.internal, "redact", "set value must be retrievable");
    assert_eq!(got.pii, "drop");
    // Reset to default to avoid contaminating other tests.
    provide_telemetry::set_classification_policy(provide_telemetry::ClassificationPolicy::default());
}

#[cfg(feature = "governance")]
#[test]
fn classification_policy_fields_are_distinct() {
    // Kills: setting all fields to the same value.
    let policy = provide_telemetry::ClassificationPolicy::default();
    assert_ne!(
        policy.pii, policy.pci,
        "pii and pci must have different default actions"
    );
    assert_ne!(
        policy.public, policy.phi,
        "public and phi must have different default actions"
    );
}
