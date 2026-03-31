# Rust Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full `undef-telemetry` API surface in Rust, passing `spec/validate_conformance.py` and sharing major.minor from `VERSION`.

**Architecture:** Built on the `tracing` ecosystem (Tokio team) with composable `Layer`s for the processor chain. OTel integration via Cargo features (`#[cfg(feature = "otel")]`) for zero-cost when disabled. All 56 required API symbols from `spec/telemetry-api.yaml` exported from the crate root.

**Tech Stack:** Rust 1.75+ (MSRV matching opentelemetry-rust), `tracing` 0.1, `tracing-subscriber` 0.3, `opentelemetry` 0.31 (optional), `tokio` 1.x, `serde`/`serde_json` 1.x, `moka` 0.12, `backon` 1.6

---

## Dependency Rationale

### Core (always included)

| Crate | Version | Role | Why this one |
|-------|---------|------|-------------|
| `tracing` | 0.1.41 | Instrumentation facade — spans + structured events | ~387M downloads. The Rust structlog. Built by Tokio team, universally adopted. |
| `tracing-core` | 0.1.x | Core `Subscriber`/`Layer` traits | Pulled transitively by `tracing` |
| `tracing-subscriber` | 0.3.x (features: `json`, `env-filter`, `fmt`) | Composable `Layer` system, JSON/text/pretty formatters, env-based filtering | ~200M downloads. The standard way to compose tracing processors. |
| `serde` | 1.x (features: `derive`) | Serialization for config, PII traversal, health snapshots | Universal in Rust. Required for JSON log output and nested PII traversal. |
| `serde_json` | 1.x | JSON serialization/deserialization | PII operates on `serde_json::Value` for untyped nested structures. |
| `regex` | 1.11+ | Pattern matching for PII rules, event name validation | ~290M downloads, extremely mature. |
| `secrecy` | 0.10.x | `Secret<T>` wrapper — `Debug`/`Display` print `[REDACTED]` | Type-level guard for sensitive config values (API keys, passwords in config). |
| `moka` | 0.12.x (features: `future`) | Concurrent cache with TTL eviction | ~15M downloads. Perfect for cardinality guards — built-in TTL, size bounds, atomic ops. |
| `backon` | 1.6+ | Retry with exponential/fibonacci backoff | Stable 1.x, async + sync, no-std compatible. Cleaner API than `backoff` crate. |
| `dashmap` | 6.x | Concurrent HashMap for shared state | ~80M downloads. Lock-free reads for hot paths (sampling policy lookups). |
| `tokio` | 1.x (features: `rt`, `macros`, `sync`, `time`) | Async runtime for timeout execution | The standard Rust async runtime. Required for timeout-based resilience. |
| `thiserror` | 2.x | Derive `Error` trait implementations | Standard for library error types in Rust. |
| `sha2` | 0.10.x | SHA-256 for PII hash mode and error fingerprinting | Pure Rust, well-audited. |

### Optional OTel (feature = "otel")

| Crate | Version | Role |
|-------|---------|------|
| `opentelemetry` | 0.31.0 | OTel API types (Tracer, Meter, SpanContext) |
| `opentelemetry_sdk` | 0.31.0 (features: `rt-tokio`) | TracerProvider, MeterProvider, BatchSpanProcessor |
| `opentelemetry-otlp` | 0.31.1 | OTLP HTTP/gRPC exporter |
| `tracing-opentelemetry` | 0.31.0 | Bridge: `tracing` spans → OTel spans |
| `opentelemetry-appender-tracing` | 0.31.x | Bridge: `tracing` events → OTel logs |

### Dev dependencies

| Crate | Role |
|-------|------|
| `tokio-test` | Async test utilities |
| `tempfile` | Temp dirs for test isolation |
| `cargo-mutants` (CLI, 26.2.0) | Mutation testing — the best in the Rust ecosystem |
| `insta` | Snapshot testing for JSON/log output |

### Not using (and why)

| Crate | Why skipped |
|-------|------------|
| `log` | Legacy — no spans, no structured data, no composable layers. `tracing` supersedes it. |
| `backoff` | Older retry crate. `backon` has cleaner API and is stable 1.x. |
| `failsafe` | Circuit breaker crate — low downloads, lightly maintained. Custom is better (~100 lines). |
| `tower` | Excellent middleware framework but overkill here — we only need retry/timeout, not the full `Service` trait. |

---

## File Structure

```
rust/
├── Cargo.toml                # Package: undef-telemetry, version = "0.4.2"
├── Cargo.lock
├── src/
│   ├── lib.rs                # Public API facade — re-exports all symbols
│   ├── config.rs             # TelemetryConfig, env var parsing
│   ├── setup.rs              # setup_telemetry / shutdown_telemetry, Mutex lifecycle
│   ├── errors.rs             # TelemetryError, ConfigurationError, EventSchemaError
│   ├── logger.rs             # tracing subscriber Layer chain, get_logger
│   ├── context.rs            # bind_context, unbind_context, clear_context (task-local storage)
│   ├── session.rs            # bind_session_context, get_session_id, clear_session_context
│   ├── tracing_provider.rs   # get_tracer, Tracer, trace wrapper, no-op fallback
│   ├── metrics.rs            # counter, gauge, histogram, get_meter, fallback impls
│   ├── propagation.rs        # extract_w3c_context, bind_propagation_context
│   ├── sampling.rs           # SamplingPolicy, set/get_sampling_policy, should_sample
│   ├── backpressure.rs       # QueuePolicy, bounded ticket system (tokio::sync::Semaphore)
│   ├── resilience.rs         # ExporterPolicy, run_with_resilience, circuit breaker
│   ├── pii.rs                # PIIRule, register/replace/get rules, sanitize_payload
│   ├── cardinality.rs        # CardinalityLimit, guard_attributes, TTL via moka
│   ├── health.rs             # HealthSnapshot, get_health_snapshot, AtomicU64 counters
│   ├── schema.rs             # event_name validation (strict/relaxed)
│   ├── slo.rs                # classify_error, record_red_metrics, record_use_metrics
│   ├── runtime.rs            # get/update/reload/reconfigure runtime config
│   ├── otel.rs               # #[cfg(feature = "otel")] — OTel provider wiring
│   └── testing.rs            # reset_for_tests functions
├── tests/
│   ├── integration_tests.rs  # Cross-module integration tests
│   ├── conformance.rs        # Verify all required exports exist
│   └── ...                   # Per-module test files
└── README.md
```

---

## Design Decisions

### OTel via Cargo features (compile-time conditional)

```toml
[features]
default = []
otel = [
    "dep:opentelemetry",
    "dep:opentelemetry_sdk",
    "dep:opentelemetry-otlp",
    "dep:tracing-opentelemetry",
]

[dependencies]
opentelemetry = { version = "0.31", optional = true }
opentelemetry_sdk = { version = "0.31", optional = true, features = ["rt-tokio"] }
opentelemetry-otlp = { version = "0.31", optional = true }
tracing-opentelemetry = { version = "0.31", optional = true }
```

Usage:
```rust
#[cfg(feature = "otel")]
fn setup_otel_tracing(config: &TelemetryConfig) -> Result<(), TelemetryError> { ... }

#[cfg(not(feature = "otel"))]
fn setup_otel_tracing(_config: &TelemetryConfig) -> Result<(), TelemetryError> {
    Ok(()) // no-op
}
```

This is zero-cost when disabled — no OTel code is even compiled.

### Processor chain via tracing-subscriber Layer composition

```rust
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;

tracing_subscriber::registry()
    .with(StandardFieldsLayer::new(config))
    .with(ErrorFingerprintLayer::new())
    .with(SamplingLayer::new(config))
    .with(SchemaEnforcementLayer::new(config))
    .with(PiiSanitizationLayer::new(config))
    .with(format_layer)  // JSON or pretty
    .init();
```

Each `Layer` implements `tracing_subscriber::Layer<S>` and can modify, filter, or drop events.

### Context propagation

Two mechanisms:
1. **tracing spans** — automatic propagation across `.await` via `Instrument` trait
2. **tokio::task_local!** — for custom per-request state (session ID, user bindings)

```rust
tokio::task_local! {
    static SESSION_ID: Option<String>;
    static BOUND_CONTEXT: HashMap<String, serde_json::Value>;
}
```

Unlike Python's contextvars, `task_local!` does NOT auto-propagate to spawned tasks. Context must be explicitly scoped:
```rust
SESSION_ID.scope(Some("sess-123".into()), async { ... }).await;
```

### Health counters — lock-free atomics

```rust
use std::sync::atomic::{AtomicU64, Ordering};

struct SignalCounters {
    queue_depth: AtomicU64,
    dropped: AtomicU64,
    retries: AtomicU64,
    export_failures: AtomicU64,
    // ...
}
```

`HealthSnapshot` is constructed by reading all atomics with `Ordering::Relaxed` (point-in-time snapshot, no need for sequential consistency).

### Error types

```rust
use thiserror::Error;

#[derive(Error, Debug)]
pub enum TelemetryError {
    #[error("configuration error: {0}")]
    Configuration(String),
    #[error("event schema error: {0}")]
    EventSchema(String),
    #[error("export error: {0}")]
    Export(#[from] Box<dyn std::error::Error + Send + Sync>),
}

// Convenience type aliases for spec conformance:
pub type ConfigurationError = TelemetryError; // variant matching
pub type EventSchemaError = TelemetryError;
```

Or use separate error structs if the spec requires distinct types.

### Circuit breaker — custom implementation

```rust
struct CircuitBreaker {
    consecutive_timeouts: AtomicU32,
    tripped_at: AtomicU64, // Instant as nanos since process start
    threshold: u32,        // 3
    cooldown: Duration,    // 30s
}

impl CircuitBreaker {
    fn is_open(&self) -> bool { ... }
    fn record_timeout(&self) { ... }
    fn reset(&self) { ... }
}
```

~100 lines, no external dependency. Per-signal instances for isolation.

---

## Task Breakdown

### Task 1: Project scaffold + config + errors

**Files:** Create: `rust/Cargo.toml`, `rust/src/lib.rs`, `rust/src/config.rs`, `rust/src/errors.rs`

- [ ] Initialize `Cargo.toml` with package name `undef-telemetry`, version `"0.4.2"`, edition 2021, MSRV 1.75
- [ ] Add core dependencies (tracing, serde, serde_json, regex, thiserror, dashmap, tokio, sha2, secrecy, moka, backon)
- [ ] Add optional OTel dependencies behind `otel` feature
- [ ] Implement `TelemetryConfig` struct with `#[derive(Clone, Debug, serde::Deserialize)]`
- [ ] Implement `TelemetryConfig::from_env()` reading all `UNDEF_*` and `OTEL_*` vars
- [ ] Implement error types: `TelemetryError`, `ConfigurationError`, `EventSchemaError`
- [ ] Create `lib.rs` with initial module declarations
- [ ] Write tests for config parsing, defaults, validation, error type conversions
- [ ] Run `cargo test`, `cargo clippy`
- [ ] Commit

### Task 2: Health + schema

**Files:** Create: `rust/src/health.rs`, `rust/src/schema.rs`

- [ ] Implement `HealthSnapshot` struct with all 25 per-signal fields
- [ ] Implement per-signal `AtomicU64` counters in a `static` or `OnceLock`-guarded struct
- [ ] Implement `get_health_snapshot()` reading all atomics
- [ ] Implement internal counter functions: `increment_dropped`, `increment_retries`, `record_export_failure`, `record_export_success`
- [ ] Implement `event_name(segments: &[&str])` with strict/relaxed mode
- [ ] Regex validation: `^[a-z][a-z0-9_]*$`, 3-5 segments in strict mode
- [ ] Write tests including boundary cases
- [ ] Commit

### Task 3: Context + session

**Files:** Create: `rust/src/context.rs`, `rust/src/session.rs`

- [ ] Define `tokio::task_local!` storage for bound context (`HashMap<String, serde_json::Value>`)
- [ ] Implement `bind_context(fields)` — scopes values into task-local
- [ ] Implement `unbind_context(keys)` — removes specific keys
- [ ] Implement `clear_context()` — clears all task-local bindings
- [ ] Define `tokio::task_local!` for session ID
- [ ] Implement `bind_session_context`, `get_session_id`, `clear_session_context`
- [ ] Write tests verifying isolation across tasks (spawn two tasks with different contexts)
- [ ] Commit

### Task 4: Sampling

**Files:** Create: `rust/src/sampling.rs`

- [ ] Implement `SamplingPolicy` struct (`default_rate: f64`, `overrides: HashMap<String, f64>`)
- [ ] Store policies in `DashMap<Signal, SamplingPolicy>` for lock-free reads
- [ ] Implement `set_sampling_policy`, `get_sampling_policy`
- [ ] Implement `should_sample(signal, key)` with `rand::random::<f64>()`, fast-paths for 0.0 and 1.0
- [ ] Wire drop counter to health module
- [ ] Write tests
- [ ] Commit

### Task 5: Backpressure

**Files:** Create: `rust/src/backpressure.rs`

- [ ] Implement `QueuePolicy` struct
- [ ] Use `tokio::sync::Semaphore` for bounded ticket system (natural async-aware semaphore)
- [ ] Implement `set_queue_policy`, `get_queue_policy`
- [ ] Implement `try_acquire(signal) -> Option<Permit>`, drop-based release
- [ ] Wire to health counters
- [ ] Write tests
- [ ] Commit

### Task 6: Resilience + circuit breaker

**Files:** Create: `rust/src/resilience.rs`

- [ ] Implement `ExporterPolicy` struct
- [ ] Implement per-signal `CircuitBreaker` (~100 lines, `AtomicU32` + `AtomicU64`)
- [ ] Implement `run_with_resilience(signal, operation)`:
  - Circuit breaker check
  - `tokio::time::timeout` for per-attempt timeout
  - `backon` for retry with exponential backoff
  - Per-signal executor isolation
- [ ] Wire to health counters
- [ ] Write tests including circuit breaker trip/half-open/reset cycle
- [ ] Commit

### Task 7: PII sanitization

**Files:** Create: `rust/src/pii.rs`

- [ ] Implement `PIIRule` struct (`path: Vec<String>`, `mode: MaskMode`, `truncate_to: usize`)
- [ ] Implement `MaskMode` enum: `Drop`, `Redact`, `Hash`, `Truncate`
- [ ] Store rules in `RwLock<Vec<PIIRule>>`
- [ ] Implement `register_pii_rule`, `replace_pii_rules`, `get_pii_rules`
- [ ] Implement `sanitize_payload(payload: &mut serde_json::Value, enabled: bool, max_depth: usize)`
- [ ] Recursive `serde_json::Value` visitor for nested maps/arrays
- [ ] Wildcard `*` segment matching
- [ ] Default sensitive key detection (case-insensitive)
- [ ] SHA-256 hash mode via `sha2` crate
- [ ] Write tests including all modes, nested structures, depth limit
- [ ] Commit

### Task 8: Cardinality guards

**Files:** Create: `rust/src/cardinality.rs`

- [ ] Implement `CardinalityLimit` struct (`max_values: usize`, `ttl: Duration`)
- [ ] Use `moka::sync::Cache` (or `moka::future::Cache` for async) for TTL-based tracking
- [ ] Implement `register_cardinality_limit`, `get_cardinality_limits`, `clear_cardinality_limits`
- [ ] Implement `guard_attributes(attrs: &mut HashMap<String, String>)` — replace overflow values with `"__overflow__"`
- [ ] Write tests including TTL expiry
- [ ] Commit

### Task 9: Logger (tracing-subscriber Layer chain)

**Files:** Create: `rust/src/logger.rs`

- [ ] Implement `StandardFieldsLayer` — adds `service`, `env`, `version` to all events
- [ ] Implement `ErrorFingerprintLayer` — computes 12-char hex fingerprint from error events
- [ ] Implement `SamplingLayer` — drops events based on `should_sample`
- [ ] Implement `SchemaEnforcementLayer` — validates event names in strict mode
- [ ] Implement `PiiSanitizationLayer` — redacts sensitive fields
- [ ] Implement `get_logger(name: &str)` — returns a span-scoped `tracing::Span` or logger handle
- [ ] Compose all layers in `configure_logging(config)`
- [ ] JSON output via `tracing_subscriber::fmt::layer().json()`
- [ ] Write tests
- [ ] Commit

### Task 10: Tracing provider

**Files:** Create: `rust/src/tracing_provider.rs`

- [ ] Implement `get_tracer(name)` — returns the global `tracing::Span` entrypoint
- [ ] Implement `trace(name, async_fn)` — wraps fn in an `info_span!` with `.instrument()`
- [ ] Implement `get_trace_context()` / `set_trace_context()` using task-local storage
- [ ] No-op fallback is implicit — without OTel layer, spans are just tracing spans
- [ ] `#[cfg(feature = "otel")]`: add `OpenTelemetryLayer` to subscriber stack
- [ ] Write tests (with and without `otel` feature)
- [ ] Commit

### Task 11: Metrics

**Files:** Create: `rust/src/metrics.rs`

- [ ] Define traits: `CounterInstrument`, `GaugeInstrument`, `HistogramInstrument`
- [ ] Implement fallback (in-process) versions using `AtomicI64`, `AtomicU64`
- [ ] `counter(name)`, `gauge(name)`, `histogram(name)` — return `Arc<dyn Instrument>`
- [ ] `get_meter(name)` — `#[cfg(feature = "otel")]` returns OTel Meter, else `None`
- [ ] Wire sampling and backpressure checks into record operations
- [ ] Write tests
- [ ] Commit

### Task 12: Propagation

**Files:** Create: `rust/src/propagation.rs`

- [ ] Implement `PropagationContext` struct
- [ ] Implement `extract_w3c_context(headers: &HeaderMap)` — parse traceparent/tracestate/baggage
- [ ] Custom parser for `00-{trace_id}-{span_id}-{flags}` (avoid OTel dep for this)
- [ ] Size guards: 512 bytes traceparent/tracestate, 8192 baggage, 32 tracestate pairs
- [ ] Implement `bind_propagation_context(ctx)` — inject into tracing span context
- [ ] `#[cfg(feature = "otel")]`: also set OTel Context for propagation
- [ ] Write tests including boundary size tests
- [ ] Commit

### Task 13: Runtime + setup/shutdown

**Files:** Create: `rust/src/runtime.rs`, `rust/src/setup.rs`

- [ ] Implement `setup_telemetry(config: Option<TelemetryConfig>) -> Result<TelemetryConfig, TelemetryError>`
- [ ] `OnceLock` or `Mutex<Option<...>>` for idempotent init
- [ ] Implement `shutdown_telemetry()` — flush providers, reset state
- [ ] Implement `get_runtime_config`, `update_runtime_config`, `reload_runtime_from_env`, `reconfigure_telemetry`
- [ ] Hot/cold config split (policies hot-reloadable, providers require restart)
- [ ] Write tests including concurrent setup from multiple threads
- [ ] Commit

### Task 14: OTel integration

**Files:** Create: `rust/src/otel.rs`

- [ ] All code gated behind `#[cfg(feature = "otel")]`
- [ ] Setup `TracerProvider` with OTLP exporter, wire to `tracing-opentelemetry` layer
- [ ] Setup `MeterProvider` with OTLP exporter
- [ ] W3C propagation via `opentelemetry_sdk::propagation::TraceContextPropagator`
- [ ] Log bridge via `opentelemetry-appender-tracing`
- [ ] Write tests (run with `--features otel`)
- [ ] Commit

### Task 15: SLO helpers (optional)

**Files:** Create: `rust/src/slo.rs`

- [ ] Implement `classify_error(exc_name: &str, status_code: Option<u16>) -> ErrorClassification`
- [ ] Implement `record_red_metrics(route, method, status_code, duration_ms)`
- [ ] Implement `record_use_metrics(resource, utilization_percent)`
- [ ] Write tests
- [ ] Commit

### Task 16: Public facade + testing

**Files:** Modify: `rust/src/lib.rs`, Create: `rust/src/testing.rs`, `rust/README.md`

- [ ] Complete `lib.rs` with all public re-exports matching spec
- [ ] Create `testing.rs` with `reset_for_tests()` functions
- [ ] Run `spec/validate_conformance.py` — must pass for Rust
- [ ] Run `scripts/check_version_sync.py` — must pass
- [ ] Write README.md following typescript/README.md structure
- [ ] Commit

### Task 17: CI integration

**Files:** Create: `.github/workflows/ci-rust.yml`

- [ ] Rust CI workflow: `cargo test`, `cargo test --features otel`, `cargo clippy`, `cargo fmt --check`
- [ ] MSRV check (1.75)
- [ ] `cargo-mutants` mutation testing
- [ ] Add to branch protection required checks
- [ ] Commit

---

## Verification

```bash
# Unit tests (no OTel)
cd rust && cargo test

# Unit tests (with OTel)
cargo test --features otel

# Clippy
cargo clippy --all-features -- -D warnings

# Format
cargo fmt --check

# Mutation testing
cargo mutants --timeout 60

# Spec conformance
uv run python spec/validate_conformance.py

# Version sync
uv run python scripts/check_version_sync.py
```

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| OTel Rust pre-1.0 version churn | Breaking changes between 0.30→0.31→0.32 | Pin exact versions in Cargo.toml, add `deny(warnings)` to catch deprecations early |
| `tracing` 0.2 migration | Major API change if/when released | Not imminent — 0.1 is the stable ecosystem API. Monitor tokio-rs/tracing repo. |
| `tracing-opentelemetry` version matrix | Must match specific `opentelemetry` versions | Document compatible version sets, test in CI |
| PII on `serde_json::Value` is slower than typed traversal | Higher latency on large payloads | Acceptable for telemetry — payloads are typically small. Profile if needed. |
| `task_local!` doesn't auto-propagate | Users forget to scope context on `tokio::spawn` | Document clearly; provide `spawn_with_context()` helper |

---

## Key Rust Idioms to Follow

1. **`Result<T, E>` for fallible operations** — never panic in library code
2. **`#[must_use]` on functions returning important values** — force callers to handle results
3. **Feature flags for optional deps** — `#[cfg(feature = "otel")]` everywhere
4. **`Arc<T>` for shared ownership** — instruments, policies are shared across threads
5. **`Send + Sync` bounds** — all public types must be thread-safe
6. **`#[derive(Clone, Debug)]` on all public types** — idiomatic Rust
7. **`impl Default for Config`** — sensible defaults for all config structs
8. **Documentation on all public items** — `///` doc comments, `#![deny(missing_docs)]`
9. **No unsafe code** — `#![forbid(unsafe_code)]` in lib.rs
