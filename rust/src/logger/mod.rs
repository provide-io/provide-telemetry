// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
use std::sync::{Arc, LazyLock, Mutex, OnceLock};

use serde_json::Value;

use crate::backpressure::{release, try_acquire};
use crate::config::TelemetryConfig;
#[cfg(feature = "governance")]
use crate::consent::should_allow;
use crate::context::get_context;
use crate::health::increment_emitted;
use crate::runtime::get_runtime_config;
use crate::sampling::{should_sample, Signal};
use crate::tracer::get_trace_context;

mod emit;
mod processors;

pub use emit::{
    enable_console_capture_for_tests, enable_json_capture_for_tests, take_console_capture,
    take_json_capture,
};
use emit::{emit_if_console, emit_if_json};
use processors::process_event;

// When the governance feature is disabled, consent is unconditionally granted.
#[cfg(not(feature = "governance"))]
#[inline(always)]
fn should_allow(_signal: &str, _level: Option<&str>) -> bool {
    true
}

const MAX_FALLBACK_EVENTS: usize = 1000;

// ---------------------------------------------------------------------------
// Programmatic config override — highest-priority, overrides env vars
// ---------------------------------------------------------------------------

static LOGGING_CONFIG_OVERRIDE: LazyLock<Mutex<Option<crate::config::LoggingConfig>>> =
    LazyLock::new(|| Mutex::new(None));

/// Override the active logging configuration programmatically.
///
/// Takes precedence over both `setup_telemetry()` config and env vars.
/// Useful when the caller wants to set level/format at startup in code
/// rather than relying solely on environment variables.
pub fn configure_logging(config: crate::config::LoggingConfig) {
    *LOGGING_CONFIG_OVERRIDE
        .lock()
        .expect("logging config override lock poisoned") = Some(config);
}

/// Clear the programmatic logging override (test helper).
pub fn reset_logging_config_for_tests() {
    *LOGGING_CONFIG_OVERRIDE
        .lock()
        .expect("logging config override lock poisoned") = None;
}

/// Read the active logging config.
///
/// Priority order:
/// 1. Programmatic override via `configure_logging()` — highest priority.
/// 2. Runtime config installed by `setup_telemetry()`.
/// 3. Fresh parse of environment variables — lowest priority / fallback.
fn active_logging_config() -> crate::config::LoggingConfig {
    if let Some(cfg) = LOGGING_CONFIG_OVERRIDE
        .lock()
        .expect("logging config override lock poisoned")
        .clone()
    {
        return cfg;
    }
    get_runtime_config()
        .map(|c| c.logging.clone())
        .unwrap_or_else(|| {
            TelemetryConfig::from_env()
                .map(|c| c.logging)
                .unwrap_or_else(|err| {
                    eprintln!(
                        "provide_telemetry: logging config parse failed, using defaults: {err}"
                    );
                    crate::config::LoggingConfig::default()
                })
        })
}

/// Shared emit path: run processors, emit (JSON + console + OTel), buffer.
fn emit_event(mut event: LogEvent) {
    process_event(&mut event);
    emit_if_json(&event);
    emit_if_console(&event);
    #[cfg(feature = "otel")]
    if crate::otel::otel_installed() {
        crate::otel::logs::emit_log(&event);
    }
    let mut buf = events().lock().expect("logger event lock poisoned");
    if buf.len() < MAX_FALLBACK_EVENTS {
        buf.push(event);
    }
    drop(buf);
}

/// Map level string to a numeric order for comparison.
/// CRITICAL/FATAL are aliases for ERROR (same severity), matching the
/// `log` bridge mapping in `level_str_to_log_filter`.
fn level_order(level: &str) -> u8 {
    match level.to_ascii_uppercase().as_str() {
        "TRACE" => 0,
        "DEBUG" => 1,
        "INFO" => 2,
        "WARN" | "WARNING" => 3,
        "ERROR" | "CRITICAL" | "FATAL" => 4,
        _ => 2, // default to INFO
    }
}

/// Resolve the effective level threshold for a given target (logger name).
/// Per-module overrides win via longest-prefix match; falls back to the
/// global default level.
fn effective_level_threshold(target: &str, config: &crate::config::LoggingConfig) -> u8 {
    let mut best_prefix_len = 0;
    let mut threshold = level_order(&config.level);
    for (prefix, lvl) in &config.module_levels {
        if target.starts_with(prefix.as_str()) && prefix.len() > best_prefix_len {
            best_prefix_len = prefix.len();
            threshold = level_order(lvl);
        }
    }
    threshold
}

/// Shared core: gate, build, process, emit, count.
fn log_event(level: &str, target: &str, message: &str) {
    // Level filtering: skip events below the effective threshold
    // (respects per-module overrides via longest-prefix match).
    let config = active_logging_config();
    if level_order(level) < effective_level_threshold(target, &config) {
        return;
    }
    if !should_allow("logs", Some(level)) {
        return;
    }
    if !should_sample(Signal::Logs, Some(message)).unwrap_or(true) {
        return;
    }
    let Some(ticket) = try_acquire(Signal::Logs) else {
        return;
    };
    emit_event(new_event(target, level, message));
    increment_emitted(Signal::Logs, 1);
    release(ticket);
}

/// Like `log_event` but attaches DARS metadata from an `Event`.
fn log_event_with_event(level: &str, target: &str, ev: &crate::schema::Event) {
    let config = active_logging_config();
    if level_order(level) < effective_level_threshold(target, &config) {
        return;
    }
    if !should_allow("logs", Some(level)) {
        return;
    }
    if !should_sample(Signal::Logs, Some(&ev.event)).unwrap_or(true) {
        return;
    }
    let Some(ticket) = try_acquire(Signal::Logs) else {
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

#[derive(Clone, Debug, PartialEq)]
pub struct LogEvent {
    pub level: String,
    pub target: String,
    pub message: String,
    pub context: BTreeMap<String, Value>,
    pub trace_id: Option<String>,
    pub span_id: Option<String>,
    pub event_metadata: Option<EventMetadata>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Logger {
    target: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NullLogger {
    target: String,
}

#[derive(Clone, Debug)]
pub struct BufferLogger {
    target: String,
    events: Arc<Mutex<Vec<LogEvent>>>,
}

static EVENTS: OnceLock<Mutex<Vec<LogEvent>>> = OnceLock::new();

fn events() -> &'static Mutex<Vec<LogEvent>> {
    EVENTS.get_or_init(|| Mutex::new(Vec::new()))
}

pub static logger: LazyLock<Logger> = LazyLock::new(|| Logger::new(None));

fn new_event(target: &str, level: &str, message: &str) -> LogEvent {
    let trace = get_trace_context();
    let mut context = get_context();
    if let Some(cfg) = get_runtime_config() {
        context.entry("service".to_string()).or_insert_with(|| Value::String(cfg.service_name));
        context.entry("env".to_string()).or_insert_with(|| Value::String(cfg.environment));
        context.entry("version".to_string()).or_insert_with(|| Value::String(cfg.version));
    }
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
            target: target.unwrap_or("provide.telemetry").to_string(),
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
        std::mem::take(&mut *events().lock().expect("logger event lock poisoned"))
    }
}

impl NullLogger {
    pub fn new(target: Option<&str>) -> Self {
        Self {
            target: target.unwrap_or("provide.telemetry").to_string(),
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
            target: target.unwrap_or("provide.telemetry").to_string(),
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
        self.events
            .lock()
            .expect("buffer logger event lock poisoned")
            .push(event);
    }

    pub fn drain(&self) -> Vec<LogEvent> {
        std::mem::take(
            &mut *self
                .events
                .lock()
                .expect("buffer logger event lock poisoned"),
        )
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

// ---------------------------------------------------------------------------
// log::Log trait — routes log::info!() / log::debug!() etc. through here
// ---------------------------------------------------------------------------

fn level_str_to_log_filter(level: &str) -> log::LevelFilter {
    match level.to_uppercase().as_str() {
        "TRACE" => log::LevelFilter::Trace,
        "DEBUG" => log::LevelFilter::Debug,
        "WARN" | "WARNING" => log::LevelFilter::Warn,
        "ERROR" | "CRITICAL" => log::LevelFilter::Error,
        _ => log::LevelFilter::Info,
    }
}

impl log::Log for Logger {
    fn enabled(&self, metadata: &log::Metadata<'_>) -> bool {
        let config = active_logging_config();
        metadata.level() <= level_str_to_log_filter(&config.level)
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
///
/// After this call all `log::info!()`, `log::debug!()` etc. macros in any
/// crate that depends on `log` will be routed through provide-telemetry.
/// Returns `Err` if a global logger has already been installed.
pub fn set_as_global_logger() -> Result<(), log::SetLoggerError> {
    log::set_logger(&*logger)?;
    log::set_max_level(log::LevelFilter::Trace);
    Ok(())
}
