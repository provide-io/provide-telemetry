# provide-telemetry/rust

SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc

Structured logging + OpenTelemetry traces and metrics for Rust — feature
parity with the [`provide-telemetry`](https://pypi.org/p/provide-telemetry)
Python, TypeScript, and Go packages.

## Install

Add to `Cargo.toml`:

```toml
[dependencies]
provide-telemetry = { path = "../rust" }          # local workspace

# or once published:
# provide-telemetry = "0.3"
```

Requires Rust 1.81+.

## Quick start

```rust
use provide_telemetry::{setup_telemetry, shutdown_telemetry, get_logger};

fn main() {
    setup_telemetry().expect("telemetry setup failed");

    let logger = get_logger(Some("myapp.handler"));
    logger.info("request.received.ok");
    logger.info_with("db.query.ok", |ctx| {
        ctx.insert("table".into(), "users".into());
        ctx.insert("rows".into(), 42.into());
    });

    shutdown_telemetry();
}
```

## API reference

### Setup

| Export | Description |
|--------|-------------|
| `setup_telemetry()` | Idempotent init from environment variables. |
| `reconfigure_telemetry(overrides)` | Hot-reload sampling / backpressure / exporter policy. |
| `shutdown_telemetry()` | Flush and shut down all providers. |
| `get_runtime_config()` | Inspect the applied config snapshot. |
| `get_runtime_status()` | Inspect provider state, fallback mode, last error. |

### Logging

```rust
let logger = get_logger(Some("api.handler"));

logger.debug("request.parsed.ok");
logger.info("request.received.ok");
logger.warn("rate.limit.approaching");
logger.error("db.query.failed");

// Attach structured fields inline
logger.info_with("user.login.ok", |ctx| {
    ctx.insert("user_id".into(), 42.into());
    ctx.insert("method".into(), "oauth".into());
});

// Attach DARS metadata (domain.action.resource.status)
use provide_telemetry::event;
let ev = event(&["auth", "login", "ok"]).expect("valid event name");
logger.info_event(&ev);
```

Event names follow the DA(R)S pattern: `event()` accepts 3–4 dot-separated
segments; `event_name()` accepts 3–5 segments.

### Tracing

```rust
use provide_telemetry::{trace, get_trace_context};

trace("db.query.ok", || {
    let ctx = get_trace_context(); // BTreeMap<String, Option<String>>
    let trace_id = ctx.get("trace_id").and_then(|v| v.as_deref());
    // ... do work ...
});
```

### Metrics

```rust
use provide_telemetry::{counter, gauge, histogram};

let reqs = counter("http.requests", None, None);
reqs.add(1.0, None);

let lat = histogram("http.duration_ms", Some("HTTP request duration"), Some("ms"));
lat.record(14.2, None);

let cpu = gauge("cpu.utilization", Some("CPU utilization ratio"), Some("percent"));
cpu.set(72.5, None);
```

### Context binding

```rust
use provide_telemetry::{bind_context, clear_context};
use std::collections::BTreeMap;

let mut fields = BTreeMap::new();
fields.insert("request_id".into(), "req-abc".into());
fields.insert("user_id".into(), 7.into());
bind_context(fields);
// All log calls on this task/thread include these fields automatically.
clear_context();
```

### Session correlation

```rust
use provide_telemetry::{bind_session_context, get_session_id, clear_session_context};

bind_session_context("sess-abc-123");
let sid = get_session_id();   // Some("sess-abc-123")
clear_session_context();
```

### W3C trace propagation

```rust
use provide_telemetry::{extract_w3c_context, bind_propagation_context, clear_propagation_context};

// In an HTTP handler — extract incoming traceparent/tracestate.
let traceparent = headers.get("traceparent").map(|v| v.to_str().unwrap_or(""));
let baggage = headers.get("baggage").map(|v| v.to_str().unwrap_or(""));
let pc = extract_w3c_context(traceparent.unwrap_or(""), baggage.unwrap_or(""));
bind_propagation_context(&pc);
// ... handle request ...
clear_propagation_context();
```

### PII sanitization

```rust
use provide_telemetry::{register_pii_rule, replace_pii_rules, sanitize_payload, PIIRule, PIIMode};
use serde_json::json;

register_pii_rule(PIIRule {
    path: vec!["user".into(), "ssn".into()],
    mode: PIIMode::Redact,
    truncate_to: 0,
});

let payload = json!({"user": {"ssn": "123-45-6789", "name": "Alice"}});
let clean = sanitize_payload(&payload, true, 8);
// clean["user"]["ssn"] == "***"
```

Built-in: redacts `password`, `token`, `secret`, `authorization`, `api_key`,
and similar keys by default.

### Health snapshot

```rust
use provide_telemetry::get_health_snapshot;

let snap = get_health_snapshot();
println!("{} logs emitted, {} retries", snap.logs_emitted, snap.retries);
```

### Testing helpers

```rust
#[cfg(test)]
mod tests {
    use provide_telemetry::testing::acquire_test_state_lock;

    #[test]
    fn my_test() {
        let _guard = acquire_test_state_lock();
        // ... test code with isolated telemetry state ...
    }
}
```

## Configuration

All options come from environment variables:

| Env var | Default | Description |
|---------|---------|-------------|
| `PROVIDE_TELEMETRY_SERVICE_NAME` | `provide-service` | Service identity |
| `PROVIDE_TELEMETRY_ENV` | `dev` | Deployment environment |
| `PROVIDE_TELEMETRY_VERSION` | `0.0.0` | Service version |
| `PROVIDE_LOG_LEVEL` | `INFO` | Log level: `TRACE` / `DEBUG` / `INFO` / `WARN` / `ERROR` |
| `PROVIDE_LOG_FORMAT` | `console` | Output format: `console` / `json` / `pretty` |
| `PROVIDE_TELEMETRY_STRICT_SCHEMA` | `false` | Enforce DA(R)S event name format |
| `PROVIDE_TRACE_ENABLED` | `true` | Enable tracing |
| `PROVIDE_TRACE_SAMPLE_RATE` | `1.0` | Trace sample rate `[0.0, 1.0]` |
| `PROVIDE_METRICS_ENABLED` | `true` | Enable metrics |
| `PROVIDE_SAMPLING_LOGS_RATE` | `1.0` | Log sampling rate `[0.0, 1.0]` |
| `PROVIDE_BACKPRESSURE_LOGS_MAXSIZE` | `1000` | Max queued log events before backpressure |
| `PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH` | `1024` | Truncate long field values at this byte count |
| `PROVIDE_SECURITY_MAX_ATTR_COUNT` | `64` | Maximum context attributes per log record |
| `PROVIDE_SECURITY_MAX_NESTING_DEPTH` | `8` | Maximum PII sanitization recursion depth |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | OTLP base endpoint (e.g. `http://localhost:4318`) |
| `OTEL_EXPORTER_OTLP_HEADERS` | — | Percent-encoded `key=value` auth headers |
| `OTEL_METRIC_EXPORT_INTERVAL` | `60000` | Metrics push interval in milliseconds (`--features otel`) |

## Cargo features

| Feature | Default | Description |
|---------|---------|-------------|
| `governance` | yes | Data governance / consent gating. Without this, `should_allow` is always true. |
| `otel` | no | Real OTLP export for traces, metrics, and logs via `opentelemetry-otlp` (HTTP/protobuf). When off, the crate provides in-process fallback instrumentation (noop tracer, in-process metrics, stderr-only logs). |
| `otel-grpc` | no | Adds gRPC transport on top of `otel`. Requires `tonic` (heavier dep tree). |

```bash
cargo build                        # default (governance, no OTel)
cargo build --features otel        # + OTLP/HTTP export
cargo build --features otel-grpc   # + OTLP/gRPC transport
cargo build --no-default-features  # minimal fallback-only build
```

## OTLP export

When built with `--features otel`, `setup_telemetry()` installs real
`TracerProvider`, `MeterProvider`, and `LoggerProvider` backed by OTLP
HTTP/protobuf exporters. All three signals (traces, metrics, logs) are
emitted to the configured endpoint:

| Env Var | Example | Notes |
|---------|---------|-------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | Shared base URL; per-signal paths (`/v1/traces`, `/v1/metrics`, `/v1/logs`) are appended automatically. |
| `OTEL_EXPORTER_OTLP_HEADERS` | `Authorization=Basic%20dXNlcjpwYXNz` | Shared auth header (percent-encoded). |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | Default. Also accepts `http/json`. `grpc` requires `--features otel-grpc`. |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | `http://traces:4318/v1/traces` | Signal-specific override (used verbatim, no path appending). |
| `OTEL_METRIC_EXPORT_INTERVAL` | `60000` | Metrics push interval in milliseconds. |

**Tokio runtime requirement:** this crate depends on `tokio` (for
`run_with_resilience` retry/timeout logic) regardless of feature flags.
With `--features otel` the SDK's batch span processor and periodic metrics
reader additionally require an active multi-threaded runtime. Call
`setup_telemetry()` from within a `#[tokio::main]` function or an
explicit `tokio::runtime::Builder` runtime:

```rust
#[tokio::main]
async fn main() {
    provide_telemetry::setup_telemetry().expect("telemetry setup");
    // ...
}
```

Architecture: `consent`, `sampling`, `backpressure`, and `resilience`
modules act as pre-filters. The OTel SDK sits behind them and handles
batching + OTLP network export only. When OTel is unconfigured or the
feature is off, the crate falls back gracefully to in-process
instrumentation (stderr logs, noop tracer, in-process counters).

## Spec conformance

This crate implements every `required: true` symbol in
[`spec/telemetry-api.yaml`](../spec/telemetry-api.yaml), with names
converted to Rust snake_case per the spec's `naming_conventions.rust` rule.

Run the conformance validator:

```bash
python3 ../spec/validate_conformance.py
```

## Examples

```bash
cargo run --example telemetry_01_basic
cargo run --example telemetry_02_w3c_propagation
cargo run --example telemetry_03_sampling_and_backpressure
cargo run --example telemetry_04_runtime_reconfigure
cargo run --example telemetry_05_pii_and_cardinality_policy
cargo run --example telemetry_06_exporter_resilience_modes
cargo run --example telemetry_07_slo_and_health_snapshot
cargo run --example telemetry_08_full_hardening_profile
cargo run --example telemetry_09_error_handling_and_degradation
cargo run --example telemetry_10_performance_metrics
cargo run --example telemetry_11_lazy_loading_proof
cargo run --example telemetry_12_error_fingerprint_and_sessions
cargo run --example telemetry_13_security_hardening
cargo run --features governance --example telemetry_14_data_governance
cargo run --features otel --example openobserve_01_emit_all_signals
cargo run --features otel --example openobserve_02_verify_ingestion
cargo run --features otel --example openobserve_03_hardening_profile
cargo run --features otel --example openobserve_04_via_public_api
cargo run --features otel --example e2e_cross_language_client
cargo run --features otel --example e2e_cross_language_server -- --port 18765
```

The example suite covers the same numbered telemetry topics as Python,
TypeScript, and Go, includes OpenObserve integration examples, and keeps
the OTLP E2E client/server pair used by the cross-language verification flow.

## Requirements

- Rust 1.81+

## Performance gate

Hot-path benchmarks (`benches/hot_path.rs`) run on every CI push as the
`performance-smoke` job, comparing per-op measurements against
`baselines/perf-rust.json` for the runner's OS bucket. Locally:
`make perf-rust`. See [`docs/PERFORMANCE.md`](../docs/PERFORMANCE.md) for
the gate's design (5x default tolerance, OS-tagged baselines) and how to
seed or refresh entries.

## Mutation testing

The Rust nightly mutation sweep is **advisory only**. It does not gate
CI the way the Python and Go mutation suites do, and the current
baseline in [`rust/mutants.out/`](./mutants.out) records a `Failure`
summary — the sweep's own build/test baseline is broken and no mutants
have been scored against it yet. Configuration lives in
[`rust/.cargo-mutants.toml`](./.cargo-mutants.toml) and
[`rust/mutants.toml`](./mutants.toml).

Re-run the sweep from `rust/`:

```bash
cargo mutants -j 4 --no-shuffle --minimum-test-timeout 20 --timeout-multiplier 4
```

This mirrors the invocation used by the `rust-mutants` job in
[`.github/workflows/ci-mutation.yml`](../.github/workflows/ci-mutation.yml).
Sweep outputs land in `rust/mutants.out/` (tracked), including
`outcomes.json`, `caught.txt`, `missed.txt`, and per-mutant logs.

## License

Apache-2.0. See [LICENSE](../LICENSES/Apache-2.0.txt).
