# provide-telemetry/rust

Structured logging + OpenTelemetry traces and metrics for Rust — feature
parity with the [`provide-telemetry`](https://pypi.org/p/provide-telemetry)
Python, TypeScript, and Go packages.

## Install

Add to `Cargo.toml`:

```toml
[dependencies]
provide-telemetry = { path = "../rust" }          # local workspace
serde_json = "1"                                  # structured log fields are serde_json::Value

# or once published:
# provide-telemetry = "0.10"
```

Requires Rust 1.81+.

## Quick start

```rust
use provide_telemetry::{get_logger, setup_telemetry, shutdown_telemetry};
use serde_json::Value;
use std::collections::BTreeMap;

fn main() {
    // None reads the configuration from the environment.
    setup_telemetry(None).expect("telemetry setup failed");

    let logger = get_logger(Some("myapp.handler"));
    logger.info("request.received.ok");

    let mut fields = BTreeMap::new();
    fields.insert("table".to_string(), Value::from("users"));
    fields.insert("rows".to_string(), Value::from(42));
    logger.info_fields("db.query.ok", &fields);

    // None uses the default shutdown timeout.
    shutdown_telemetry(None).expect("telemetry shutdown failed");
}
```

## API reference

### Setup

| Export | Description |
|--------|-------------|
| `setup_telemetry(Option<TelemetryConfig>) -> Result<TelemetryConfig, TelemetryError>` | Idempotent init; `None` reads the environment. |
| `reconfigure_telemetry(Option<TelemetryConfig>)` | Apply a new config (`None` re-reads the environment); provider-changing fields are an error while OTel providers are installed. |
| `update_runtime_config(RuntimeOverrides)` | Hot-reload sampling / backpressure / exporter policy. |
| `set_log_output(writer)` / `clear_log_output()` | Send rendered log records to any `Write + Send` instead of stderr, and back. Colour is off while a writer is installed; reconfiguration does not touch it. |
| `flush_telemetry(Option<f64>) -> Result<(), TelemetryError>` | Drain every installed provider and leave them installed; the argument is a timeout in seconds. |
| `adopt_global_providers(AdoptedProviders)` | Tell the facade the host installed live providers on the OTel globals, so emission routes through them. Rust cannot detect this for itself. |
| `shutdown_telemetry(Option<f64>) -> Result<(), TelemetryError>` | Flush and shut down all providers; the argument is a timeout in seconds. |
| `get_runtime_config() -> Option<TelemetryConfig>` | Inspect the applied config snapshot; `None` before setup. |
| `get_runtime_status() -> RuntimeStatus` | Inspect provider state, fallback mode, last error. |

### Logging

```rust
let logger = get_logger(Some("api.handler"));

logger.debug("request.parsed.ok");
logger.info("request.received.ok");
logger.warn("rate.limit.approaching");
logger.error("db.query.failed");

// Attach structured fields
let mut fields = BTreeMap::new();
fields.insert("user_id".to_string(), Value::from(42));
fields.insert("method".to_string(), Value::from("oauth"));
logger.info_fields("user.login.ok", &fields);

// Attach DARS metadata (domain.action.resource.status)
use provide_telemetry::event;
let ev = event(&["auth", "login", "ok"]).expect("valid event name");
logger.info_event(&ev);
```

Event names follow the DA(R)S pattern: `event()` accepts 3–4 segments in
every mode. `event_name()` accepts one or more non-empty segments by default,
and 3–5 segments matching `^[a-z][a-z0-9_]*$` under
`PROVIDE_TELEMETRY_STRICT_SCHEMA=true`.

The SDK stamps the service identity (`service`, `env`, `version`) and, while a
span is live, `trace_id` and `span_id` on every record. A caller or bound
field under one of those names is replaced by the stamped value, not
duplicated; to name a remote service, use `peer.service`.

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

Observable instruments report through a callback that runs at each collection
(every Prometheus scrape, every OTLP export interval). Create them after
`setup_telemetry()`: without a provider the callback never runs.

```rust
use provide_telemetry::{observable_gauge, Observation};

let depth = observable_gauge(
    "queue.depth",
    move || vec![Observation::new(queue.len() as f64)],
    None, // description
    None, // unit
);
// ... later ...
depth.unregister();
```

`observable_counter` and `observable_up_down_counter` take the same arguments.

### Prometheus

Built with `--features otel`, the crate can serve its metrics for Prometheus
to pull. Add `prometheus` to `OTEL_METRICS_EXPORTER` (`prometheus` alone, or
`otlp,prometheus` to push as well), then call the framework-neutral handler
from your own HTTP server and write back its status, headers and body:

```rust
let response = provide_telemetry::metrics_handler(method, accept); // (&str, Option<&str>)
// response.status: u16, response.headers: Vec<(&str, String)>, response.body: Vec<u8>
```

It serves `GET` and `HEAD` (405 otherwise) and answers 503 with a one-line
reason before setup, after shutdown, with metrics disabled, or when the reader
was not selected. `render_prometheus(accept)` returns `(body, content_type)`
for servers that want only the payload.

With the `prometheus-listener` feature, `PROVIDE_METRICS_PROMETHEUS_LISTEN=true`
(or `auto`) starts a standalone listener on `127.0.0.1:9464/metrics`
(`OTEL_EXPORTER_PROMETHEUS_HOST`, `OTEL_EXPORTER_PROMETHEUS_PORT`,
`PROVIDE_METRICS_PROMETHEUS_PATH`), with TLS and basic auth from
`PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG`. Without the feature, asking for the
listener sets the health snapshot's `setup_error` instead. Every scrape also
carries the SDK's own health as `provide_telemetry_*` series;
`PROVIDE_METRICS_HEALTH_OTLP=true` exports them over OTLP as well. See
[docs/guide/configuration.md](../docs/guide/configuration.md) for the web
config format.

### Context binding

```rust
use provide_telemetry::{bind_context, clear_context};
use serde_json::Value;

let _bound = bind_context([
    ("request_id", Value::from("req-abc")),
    ("user_id", Value::from(7)),
]);
// Log calls on this thread include these fields until `_bound` drops.
let _cleared = clear_context(); // also scoped: dropping it restores the fields
```

Every binding function returns a guard that restores the previous context when
it drops, so hold it for as long as the binding should last; a bare
`bind_context(...);` is undone at the end of the statement.

### Session correlation

```rust
use provide_telemetry::{bind_session_context, get_session_id, clear_session_context};

let _session = bind_session_context("sess-abc-123");
let sid = get_session_id();   // Some("sess-abc-123")
let _cleared = clear_session_context();
```

### W3C trace propagation

```rust
use provide_telemetry::{extract_w3c_context, bind_propagation_context};

// In an HTTP handler — extract incoming traceparent/tracestate/baggage.
let header = |name: &str| headers.get(name).and_then(|v| v.to_str().ok());
let pc = extract_w3c_context(header("traceparent"), header("tracestate"), header("baggage"));
let _propagation = bind_propagation_context(pc);
// ... handle request; the binding is undone when `_propagation` drops ...
```

### PII sanitization

```rust
use provide_telemetry::{register_pii_rule, replace_pii_rules, sanitize_payload, PIIRule, PIIMode};
use serde_json::json;

register_pii_rule(PIIRule {
    path: vec!["user".into(), "ssn".into()],
    mode: PIIMode::Redact,
    ..Default::default() // truncate_to: DEFAULT_TRUNCATE_TO (8), used by Truncate rules
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
println!("{} logs emitted, {} retries", snap.emitted_logs, snap.retries_logs);
```

A log record counts in `emitted_logs` once it has passed the sinks. One
refused before export — by consent, sampling or backpressure — counts in
`dropped_logs` instead, never in both.

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
| `PROVIDE_LOG_LEVEL` | `INFO` | Log level: `TRACE` / `DEBUG` / `INFO` / `WARN` (or `WARNING`) / `ERROR` / `CRITICAL` |
| `PROVIDE_LOG_FORMAT` | `console` | Output format: `console` / `json` / `pretty` |
| `PROVIDE_LOG_PRETTY_KEY_COLOR` | `dim` | ANSI color name for keys in pretty format |
| `PROVIDE_LOG_PRETTY_VALUE_COLOR` | `""` | ANSI color name for values in pretty format |
| `PROVIDE_LOG_PRETTY_FIELDS` | `""` | Comma-separated field names to display in pretty format |
| `PROVIDE_TELEMETRY_STRICT_SCHEMA` | `false` | Enforce DA(R)S event name format |
| `PROVIDE_TRACE_ENABLED` | `true` | Enable tracing |
| `PROVIDE_TRACE_SAMPLE_RATE` | `1.0` | Trace sample rate `[0.0, 1.0]` |
| `PROVIDE_METRICS_ENABLED` | `true` | Enable metrics |
| `PROVIDE_SAMPLING_LOGS_RATE` | `1.0` | Log sampling rate `[0.0, 1.0]` |
| `PROVIDE_BACKPRESSURE_LOGS_MAXSIZE` | `0` | Max queued log events before backpressure (`0` = unlimited) |
| `PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH` | `1024` | Truncate long field values at this byte count |
| `PROVIDE_SECURITY_MAX_ATTR_COUNT` | `64` | Maximum context attributes per log record |
| `PROVIDE_SECURITY_MAX_NESTING_DEPTH` | `8` | Maximum PII sanitization recursion depth |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | OTLP base endpoint (e.g. `http://localhost:4318`) |
| `OTEL_EXPORTER_OTLP_HEADERS` | — | Percent-encoded `key=value` auth headers |
| `OTEL_METRIC_EXPORT_INTERVAL` | `60000` | Metrics push interval in milliseconds (`--features otel`) |
| `OTEL_METRICS_EXPORTER` | `otlp` | Comma-separated: `otlp`, `prometheus`, `none` (see [Prometheus](#prometheus)) |

The full list, including the Prometheus variables, is in
[docs/guide/configuration.md](../docs/guide/configuration.md).

## Cargo features

| Feature | Default | Description |
|---------|---------|-------------|
| `otel` | no | Real OTLP export for traces, metrics, and logs via `opentelemetry-otlp` (HTTP/protobuf). When off, the crate provides in-process fallback instrumentation (noop tracer, in-process metrics, stderr-only logs). |
| `otel-grpc` | no | Adds gRPC transport on top of `otel`. Requires `tonic` (heavier dep tree). |
| `prometheus-listener` | no | The standalone Prometheus listener (`PROVIDE_METRICS_PROMETHEUS_LISTEN`), with TLS (rustls) and bcrypt basic auth from the web config. Implies `otel`. |

```bash
cargo build                                  # default (fallback-only)
cargo build --features otel                  # + OTLP/HTTP export and the Prometheus handler
cargo build --features otel-grpc             # + OTLP/gRPC transport
cargo build --features prometheus-listener   # + standalone Prometheus listener
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
| `OTEL_EXPORTER_OTLP_CERTIFICATE` | `/etc/ssl/private-ca.crt` | PEM CA bundle for TLS; `_CLIENT_CERTIFICATE` / `_CLIENT_KEY` add mutual TLS. Each has per-signal forms (`OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE`, ...) that win. |
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
    provide_telemetry::setup_telemetry(None).expect("telemetry setup");
    // ...
}
```

A certificate or key that cannot be read or loaded leaves that signal's
exporter unbuilt, logs `otlp.tls_file_unreadable` and sets the health
snapshot's `setup_error`; setup still succeeds and the other signals are
unaffected.

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
cargo run --example telemetry_14_data_governance
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

## Coverage gate

Rust CI enforces zero uncovered project lines with `cargo-llvm-cov`.
The gate ignores Rust standard-library source paths only; missed lines in
`rust/` fail the workflow. Locally:

```bash
RUST_TEST_THREADS=1 cargo llvm-cov --all-targets --all-features --ignore-filename-regex '/rustlib/src/rust/library/|/\.rustup/|/toolchains/' --fail-uncovered-lines 0 --fail-under-functions 100
```

## Performance gate

Hot-path benchmarks (`benches/hot_path.rs`) run on every CI push as the
`performance-smoke` job, comparing per-op measurements against
`baselines/perf-rust.json` for the runner's OS bucket. Locally:
`make perf-rust`. See [`docs/internal/quality-gates.md`](../docs/internal/quality-gates.md) for
the gate's design (5x default tolerance, OS-tagged baselines) and how to
seed or refresh entries.

## Mutation testing

Rust changes are gated by a complete all-feature `cargo-mutants` sweep with
a 100% kill requirement. Equivalent mutations must be narrowly documented in
[`rust/.cargo/mutants.toml`](./.cargo/mutants.toml) or at the source site; the
gate does not permit surviving or timed-out behavioral mutants.

Re-run the sweep from `rust/`:

```bash
CARGO_BUILD_JOBS=1 NEXTEST_TEST_THREADS=1 CARGO_PROFILE_TEST_DEBUG=0 \
  cargo mutants --in-place --all-features --test-tool nextest \
  --jobserver-tasks 1 --no-shuffle \
  --minimum-test-timeout 300 --timeout-multiplier 4
```

This uses the same memory-bounded compiler, test-runner, and mutation-worker
limits as each Rust mutation shard in
[`.github/workflows/ci-mutation.yml`](../.github/workflows/ci-mutation.yml).
Sweep outputs land in `rust/mutants.out/`, including
`outcomes.json`, `caught.txt`, `missed.txt`, and per-mutant logs.

## License

Apache-2.0. See [LICENSE](../LICENSES/Apache-2.0.txt).
