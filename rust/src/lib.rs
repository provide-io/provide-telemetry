// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#![allow(non_upper_case_globals)]

pub mod backpressure;
pub mod cardinality;
#[cfg(feature = "governance")]
pub mod classification;
mod config;
#[cfg(feature = "governance")]
pub mod consent;
pub mod context;
mod errors;
pub mod fingerprint;
pub mod health;
pub mod logger;
pub mod metrics;
pub mod otel;
pub mod pii;
mod policies;
pub mod propagation;
#[cfg(feature = "governance")]
pub mod receipts;
pub mod resilience;
mod runtime;
pub mod sampling;
pub mod schema;
mod secret_patterns_generated;
mod setup;
pub mod slo;
pub mod testing;
pub mod tracer;

pub use backpressure::{get_queue_policy, release, set_queue_policy, try_acquire, QueuePolicy};
pub use cardinality::{
    clear_cardinality_limits, get_cardinality_limits, guard_attributes, register_cardinality_limit,
    CardinalityLimit,
};
#[cfg(feature = "governance")]
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
#[cfg(feature = "governance")]
pub use consent::{
    get_consent_level, reset_consent_for_tests, set_consent_level, should_allow, ConsentLevel,
};
pub use context::{
    bind_context, bind_session_context, clear_context, clear_session_context, get_session_id,
    unbind_context,
};
pub use errors::{ConfigurationError, EventSchemaError, TelemetryError};
pub use fingerprint::compute_error_fingerprint;
pub use health::{get_health_snapshot, HealthSnapshot};
pub use logger::{
    buffer_logger, configure_logging, enable_console_capture_for_tests,
    enable_json_capture_for_tests, get_logger, logger, null_logger, reset_logging_config_for_tests,
    set_as_global_logger, take_console_capture, take_json_capture, BufferLogger, EventMetadata,
    LogEvent, Logger, NullLogger,
};
pub use metrics::{
    counter, gauge, get_meter, histogram, reset_metrics_for_tests, Counter, Gauge, Histogram, Meter,
};
pub use otel::{_reset_otel_for_tests, otel_installed_for_tests};
pub use pii::{
    get_pii_rules, get_secret_patterns, register_pii_rule, register_secret_pattern,
    replace_pii_rules, reset_secret_patterns_for_tests, sanitize_payload, PIIMode, PIIRule,
    SecretPattern,
};
pub use propagation::{
    bind_propagation_context, extract_w3c_context, parse_baggage, PropagationContext,
};
#[cfg(feature = "governance")]
pub use receipts::{
    enable_receipts, get_emitted_receipts_for_tests, reset_receipts_for_tests, RedactionReceipt,
};
pub use resilience::{
    get_circuit_state, get_exporter_policy, run_with_resilience, set_exporter_policy,
    ExporterPolicy,
};
pub use runtime::{
    get_runtime_config, get_runtime_status, reconfigure_telemetry, reload_runtime_from_env,
    update_runtime_config, RuntimeStatus, SignalStatus,
};
pub use sampling::{
    get_sampling_policy, set_sampling_policy, should_sample, SamplingPolicy, Signal,
};
pub use schema::{
    event, event_name, get_strict_schema, set_strict_schema, validate_required_keys, Event,
};
pub use setup::{setup_telemetry, shutdown_telemetry};
pub use slo::{classify_error, record_red_metrics, record_use_metrics, reset_slo_for_tests};
pub use tracer::{
    get_trace_context, get_tracer, set_trace_context, trace, tracer, NoopSpan, Tracer,
};
