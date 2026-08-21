// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#![allow(non_upper_case_globals)]

mod _lock;
pub mod backpressure;
pub mod cardinality;
pub mod classification;
mod config;
pub mod consent;
pub mod context;
mod errors;
pub mod fingerprint;
mod harden;
pub mod health;
mod jcs;
pub mod logger;
pub mod metrics;
pub mod otel;
pub mod pii;
mod policies;
pub mod propagation;
pub mod receipts;
pub mod resilience;
mod runtime;
mod runtime_facade;
pub mod sampling;
pub mod schema;
mod secret_patterns_generated;
mod setup;
pub mod slo;
pub mod testing;
pub mod tracer;
pub mod tracing;

pub use backpressure::{get_queue_policy, release, set_queue_policy, try_acquire, QueuePolicy};
pub use cardinality::{
    clear_cardinality_limits, get_cardinality_limits, guard_attributes, register_cardinality_limit,
    CardinalityLimit,
};
pub use classification::{
    classify_key, clear_classification_rules, get_classification_policy,
    register_classification_rule, register_classification_rules, set_classification_policy,
    ClassificationPolicy, ClassificationRule, DataClass,
};
pub use config::{
    redact_config, BackpressureConfig, EventSchemaConfig, ExporterPolicyConfig, LoggingConfig,
    MetricsConfig, RuntimeOverrides, SLOConfig, SamplingConfig, SecurityConfig, TelemetryConfig,
    TracingConfig,
};
pub use consent::{
    get_consent_level, load_consent_from_env, reset_consent_for_tests, set_consent_level,
    should_allow, ConsentLevel,
};
pub use context::{
    bind_context, bind_session_context, clear_context, clear_session_context, get_session_id,
    unbind_context,
};
pub use errors::{
    provider_immutable_error, ConfigurationError, EventSchemaError, ProviderImmutableError,
    TelemetryError,
};
pub use fingerprint::compute_error_fingerprint;
pub use health::{get_health_snapshot, HealthSnapshot};
pub use logger::levels::{level_order, parse_level, try_parse_level, LogSeverity};
pub use logger::{
    buffer_logger, configure_logging, enable_console_capture_for_tests,
    enable_json_capture_for_tests, enable_pretty_capture_for_tests, get_logger, logger,
    null_logger, reset_logging_config_for_tests, set_as_global_logger, take_console_capture,
    take_json_capture, take_pretty_capture, BufferLogger, EventMetadata, LogEvent, Logger,
    NullLogger,
};
pub use metrics::{
    counter, gauge, get_meter, histogram, reset_metrics_for_tests, Counter, Gauge, Histogram, Meter,
};
pub use otel::adopt::{adopt_global_providers, adopted_global_providers, AdoptedProviders};
pub use otel::{_reset_otel_for_tests, otel_installed_for_tests};
pub use pii::{
    get_pii_rules, get_secret_patterns, register_pii_rule, register_secret_pattern,
    replace_pii_rules, reset_secret_patterns_for_tests, sanitize_payload, PIIMode, PIIRule,
    SecretPattern, DEFAULT_TRUNCATE_TO,
};
pub use propagation::{
    bind_propagation_context, extract_w3c_context, parse_baggage, PropagationContext,
};
pub use receipts::{
    canonical_json, canonical_number, emit_receipt, enable_receipts,
    get_emitted_receipts_for_tests, receipt_payload, reset_receipts_for_tests, sign_receipt,
    ReceiptOptions, ReceiptSink, RedactionReceipt, SignReceiptOptions, TestReceiptCollector,
    TEST_RECEIPT_CAPACITY,
};
pub use resilience::{
    get_circuit_state, get_exporter_policy, run_with_resilience, set_exporter_policy,
    ExporterPolicy,
};
pub use runtime::{
    flush_result, get_runtime_config, get_runtime_status, provider_mode, reconfigure_result,
    reconfigure_telemetry, reload_runtime_from_env, runtime_state, runtime_status,
    signal_flush_result, telemetry_config, telemetry_runtime, update_runtime_config, FlushResult,
    ProviderMode, ReconfigureResult, RuntimeState, RuntimeStatus, SignalFlushResult, SignalStatus,
    TelemetryRuntime,
};
pub use sampling::{
    get_sampling_policy, set_sampling_policy, should_sample, SamplingPolicy, Signal,
};
pub use schema::{
    event, event_name, get_strict_schema, set_strict_schema, validate_required_keys, Event,
};
pub use setup::{flush_telemetry, setup_telemetry, shutdown_telemetry};
pub use slo::{
    classify_error, get_error_count_for_tests, get_request_count_for_tests, record_red_metrics,
    record_use_metrics, reset_slo_for_tests, slo_initialized_for_tests,
};
pub use tracer::{
    get_trace_context, get_tracer, set_trace_context, trace, tracer, NoopSpan, Tracer,
};
