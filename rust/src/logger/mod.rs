// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
use std::sync::{Arc, LazyLock, Mutex, OnceLock};

use serde_json::Value;

use crate::backpressure::{release, try_acquire, QueueTicket};
use crate::config::TelemetryConfig;
#[cfg(feature = "governance")]
use crate::consent::should_allow;
use crate::context::get_context;
use crate::health::increment_emitted;
use crate::runtime::get_runtime_config;
use crate::sampling::{should_sample, Signal};
use crate::tracer::get_trace_context;

mod emit;
mod levels;
mod pretty;
mod processors;

use emit::{emit_if_console, emit_if_json, emit_if_otel, emit_if_pretty};
pub use emit::{
    enable_console_capture_for_tests, enable_json_capture_for_tests,
    enable_pretty_capture_for_tests, take_console_capture, take_json_capture, take_pretty_capture,
};
use levels::{effective_level_threshold, level_order};
use processors::process_event;

#[cfg(feature = "governance")]
#[inline(always)]
fn consent_allows_logs(level: &str) -> bool {
    should_allow("logs", Some(level))
}

#[cfg(not(feature = "governance"))]
#[inline(always)]
#[cfg_attr(test, mutants::skip)] // Dead under the default governance feature set, so false-return mutants are not meaningfully testable here.
fn consent_allows_logs(_level: &str) -> bool {
    true
}

const MAX_FALLBACK_EVENTS: usize = 1000;

static LOGGING_CONFIG_OVERRIDE: LazyLock<Mutex<Option<crate::config::LoggingConfig>>> =
    LazyLock::new(|| Mutex::new(None));

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only rewrite Vec::new() syntax.
fn empty_events_mutex() -> Mutex<Vec<LogEvent>> {
    Mutex::new(Vec::new())
}

/// Override the active logging configuration programmatically.
///
/// Takes precedence over both `setup_telemetry()` config and env vars.
/// Useful when the caller wants to set level/format at startup in code
/// rather than relying solely on environment variables.
pub fn configure_logging(config: crate::config::LoggingConfig) {
    *crate::_lock::lock(&LOGGING_CONFIG_OVERRIDE) = Some(config);
}

/// Clear the programmatic logging override (test helper).
pub fn reset_logging_config_for_tests() {
    *crate::_lock::lock(&LOGGING_CONFIG_OVERRIDE) = None;
}

/// Read the active logging config.
/// Priority order: programmatic override, runtime config, then env/defaults.
fn active_logging_config() -> crate::config::LoggingConfig {
    let override_cfg = crate::_lock::lock(&LOGGING_CONFIG_OVERRIDE).clone();
    if let Some(cfg) = override_cfg {
        return cfg;
    }
    if let Some(cfg) = get_runtime_config() {
        return cfg.logging.clone();
    }
    match TelemetryConfig::from_env() {
        Ok(cfg) => cfg.logging,
        Err(err) => {
            eprintln!("provide_telemetry: logging config parse failed, using defaults: {err}");
            crate::config::LoggingConfig::default()
        }
    }
}

fn runtime_identity_config() -> Option<TelemetryConfig> {
    match get_runtime_config() {
        Some(cfg) => Some(cfg),
        None => TelemetryConfig::from_env().ok(),
    }
}

fn inject_identity_fields(context: &mut BTreeMap<String, Value>, cfg: TelemetryConfig) {
    context
        .entry("service".to_string())
        .or_insert(Value::String(cfg.service_name));
    context
        .entry("env".to_string())
        .or_insert(Value::String(cfg.environment));
    context
        .entry("version".to_string())
        .or_insert(Value::String(cfg.version));
}

fn inject_runtime_identity_fields(context: &mut BTreeMap<String, Value>) {
    let cfg = match runtime_identity_config() {
        Some(cfg) => cfg,
        None => return,
    };
    inject_identity_fields(context, cfg);
}

/// Shared emit path: run processors, emit, buffer.
fn emit_event(mut event: LogEvent) {
    process_event(&mut event);
    emit_if_json(&event);
    emit_if_pretty(&event);
    emit_if_console(&event);
    emit_if_otel(&event);
    let mut buf = crate::_lock::lock(events());
    if buf.len() >= MAX_FALLBACK_EVENTS {
        return;
    }
    buf.push(event);
}

fn acquire_log_ticket(level: &str, target: &str, sample_key: Option<&str>) -> Option<QueueTicket> {
    let config = active_logging_config();
    if level_order(level) < effective_level_threshold(target, &config) {
        return None;
    }
    if !consent_allows_logs(level) {
        return None;
    }
    if !should_sample(Signal::Logs, sample_key).unwrap_or(true) {
        return None;
    }
    try_acquire(Signal::Logs)
}

/// Like `log_event` but merges extra caller-supplied fields into the event context.
fn log_event_with_fields(
    level: &str,
    target: &str,
    message: &str,
    extra: &BTreeMap<String, Value>,
) {
    let Some(ticket) = acquire_log_ticket(level, target, Some(message)) else {
        return;
    };
    let mut event = new_event(target, level, message);
    event.context.extend(extra.clone());
    emit_event(event);
    increment_emitted(Signal::Logs, 1);
    release(ticket);
}

/// Shared core: gate, build, process, emit, count.
fn log_event(level: &str, target: &str, message: &str) {
    let Some(ticket) = acquire_log_ticket(level, target, Some(message)) else {
        return;
    };
    emit_event(new_event(target, level, message));
    increment_emitted(Signal::Logs, 1);
    release(ticket);
}

/// Like `log_event` but attaches DARS metadata from an `Event`.
fn log_event_with_event(level: &str, target: &str, ev: &crate::schema::Event) {
    let Some(ticket) = acquire_log_ticket(level, target, Some(&ev.event)) else {
        return;
    };
    let mut event = new_event(target, level, &ev.event);
    event.event_metadata = Some(EventMetadata {
        domain: ev.domain.clone(),
        action: ev.action.clone(),
        resource: ev.resource.clone(),
        status: ev.status.clone(),
    });
    emit_event(event);
    increment_emitted(Signal::Logs, 1);
    release(ticket);
}

/// DARS metadata extracted from an `Event` when the caller uses the
/// `_event` logger methods. `None` for plain string messages.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EventMetadata {
    pub domain: String,
    pub action: String,
    pub resource: Option<String>,
    pub status: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LogEvent {
    pub level: String,
    pub target: String,
    pub message: String,
    pub context: BTreeMap<String, Value>,
    pub trace_id: Option<String>,
    pub span_id: Option<String>,
    pub event_metadata: Option<EventMetadata>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Logger {
    target: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NullLogger {
    target: String,
}

#[derive(Clone, Debug, Default)]
pub struct BufferLogger {
    target: String,
    events: Arc<Mutex<Vec<LogEvent>>>,
}

static EVENTS: OnceLock<Mutex<Vec<LogEvent>>> = OnceLock::new();

fn events() -> &'static Mutex<Vec<LogEvent>> {
    EVENTS.get_or_init(empty_events_mutex)
}

fn default_logger() -> Logger {
    Logger::new(None)
}

pub static logger: LazyLock<Logger> = LazyLock::new(default_logger);

fn logger_target(target: Option<&str>) -> String {
    match target {
        Some(target) => target.to_string(),
        None => "provide.telemetry".to_string(),
    }
}

fn new_event(target: &str, level: &str, message: &str) -> LogEvent {
    let trace = get_trace_context();
    let mut context = get_context();
    inject_runtime_identity_fields(&mut context);
    LogEvent {
        level: level.to_string(),
        target: target.to_string(),
        message: message.to_string(),
        context,
        trace_id: trace.get("trace_id").and_then(Clone::clone),
        span_id: trace.get("span_id").and_then(Clone::clone),
        event_metadata: None,
    }
}

impl Logger {
    pub fn new(target: Option<&str>) -> Self {
        Self {
            target: logger_target(target),
        }
    }

    pub fn target(&self) -> &str {
        &self.target
    }

    pub fn debug(&self, message: &str) {
        self.log("DEBUG", message);
    }

    pub fn info(&self, message: &str) {
        self.log("INFO", message);
    }

    pub fn warn(&self, message: &str) {
        self.log("WARN", message);
    }

    pub fn error(&self, message: &str) {
        self.log("ERROR", message);
    }

    pub fn log(&self, level: &str, message: &str) {
        log_event(level, &self.target, message);
    }

    /// Emit with extra step-local structured fields merged into the event context.
    pub fn log_fields(&self, level: &str, message: &str, fields: &BTreeMap<String, Value>) {
        log_event_with_fields(level, &self.target, message, fields);
    }

    pub fn debug_fields(&self, message: &str, fields: &BTreeMap<String, Value>) {
        self.log_fields("DEBUG", message, fields);
    }

    pub fn info_fields(&self, message: &str, fields: &BTreeMap<String, Value>) {
        self.log_fields("INFO", message, fields);
    }

    pub fn warn_fields(&self, message: &str, fields: &BTreeMap<String, Value>) {
        self.log_fields("WARN", message, fields);
    }

    pub fn error_fields(&self, message: &str, fields: &BTreeMap<String, Value>) {
        self.log_fields("ERROR", message, fields);
    }

    pub fn debug_event(&self, event: &crate::schema::Event) {
        self.log_event("DEBUG", event);
    }

    pub fn info_event(&self, event: &crate::schema::Event) {
        self.log_event("INFO", event);
    }

    pub fn warn_event(&self, event: &crate::schema::Event) {
        self.log_event("WARN", event);
    }

    pub fn error_event(&self, event: &crate::schema::Event) {
        self.log_event("ERROR", event);
    }

    pub fn log_event(&self, level: &str, event: &crate::schema::Event) {
        log_event_with_event(level, &self.target, event);
    }

    pub fn drain_events_for_tests() -> Vec<LogEvent> {
        std::mem::take(&mut *crate::_lock::lock(events()))
    }
}

impl NullLogger {
    pub fn new(target: Option<&str>) -> Self {
        Self {
            target: logger_target(target),
        }
    }

    pub fn target(&self) -> &str {
        &self.target
    }

    pub fn debug(&self, _message: &str) {}

    pub fn info(&self, _message: &str) {}

    pub fn warn(&self, _message: &str) {}

    pub fn error(&self, _message: &str) {}
}

impl BufferLogger {
    pub fn new(target: Option<&str>) -> Self {
        Self {
            target: logger_target(target),
            events: Arc::new(Mutex::new(Vec::new())),
        }
    }

    pub fn target(&self) -> &str {
        &self.target
    }

    pub fn debug(&self, message: &str) {
        self.log("DEBUG", message);
    }

    pub fn info(&self, message: &str) {
        self.log("INFO", message);
    }

    pub fn warn(&self, message: &str) {
        self.log("WARN", message);
    }

    pub fn error(&self, message: &str) {
        self.log("ERROR", message);
    }

    pub fn log(&self, level: &str, message: &str) {
        let config = active_logging_config();
        if level_order(level) < effective_level_threshold(&self.target, &config) {
            return;
        }
        let mut event = new_event(&self.target, level, message);
        process_event(&mut event);
        crate::_lock::lock(&self.events).push(event);
    }

    pub fn drain(&self) -> Vec<LogEvent> {
        std::mem::take(&mut *crate::_lock::lock(&self.events))
    }
}

pub fn get_logger(name: Option<&str>) -> Logger {
    Logger::new(name)
}

pub fn null_logger(name: Option<&str>) -> NullLogger {
    NullLogger::new(name)
}

pub fn buffer_logger(name: Option<&str>) -> BufferLogger {
    BufferLogger::new(name)
}

impl log::Log for Logger {
    fn enabled(&self, metadata: &log::Metadata<'_>) -> bool {
        let config = active_logging_config();
        let record_order: u8 = match metadata.level() {
            log::Level::Error => 4,
            log::Level::Warn => 3,
            log::Level::Info => 2,
            log::Level::Debug => 1,
            log::Level::Trace => 0,
        };
        record_order >= effective_level_threshold(metadata.target(), &config)
    }

    fn log(&self, record: &log::Record<'_>) {
        if !self.enabled(record.metadata()) {
            return;
        }
        let level = match record.level() {
            log::Level::Error => "ERROR",
            log::Level::Warn => "WARN",
            log::Level::Info => "INFO",
            log::Level::Debug => "DEBUG",
            log::Level::Trace => "TRACE",
        };
        log_event(level, record.target(), &record.args().to_string());
    }

    fn flush(&self) {}
}

/// Register the package-level logger as the global `log` crate backend.
pub fn set_as_global_logger() -> Result<(), log::SetLoggerError> {
    match log::set_logger(&*logger) {
        Ok(()) => {
            log::set_max_level(log::LevelFilter::Trace);
            Ok(())
        }
        Err(err) => Err(err),
    }
}

#[cfg(test)]
mod tests;

#[cfg(test)]
#[path = "log_trait_tests.rs"]
mod log_trait_tests;
