# Rust Crate

`provide-telemetry` ships a Rust crate in this repo under `rust/`.

## Cargo Features

| Feature | Default | Description |
|---|---|---|
| `governance` | yes | Data governance / consent gating. Without this, `should_allow` is always true. |
| `otel` | no | Real OTLP export for traces, metrics, and logs via `opentelemetry-otlp` (HTTP/protobuf). When off, the crate provides in-process fallback instrumentation (noop tracer, in-process metrics, stderr-only logs). |
| `otel-grpc` | no | Adds gRPC transport on top of `otel`. Requires `tonic` (heavier dep tree). |

```bash
cargo build                        # default (governance, no OTel)
cargo build --features otel        # + OTLP/HTTP export
cargo build --features otel-grpc   # + OTLP/gRPC transport
cargo build --no-default-features  # minimal fallback-only build
```

## OTLP Export

When built with `--features otel`, `setup_telemetry()` installs real
`TracerProvider`, `MeterProvider`, and `LoggerProvider` backed by OTLP
HTTP/protobuf exporters. All three signals (traces, metrics, logs) are
emitted to the configured endpoint:

| Env Var | Example | Notes |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | Shared base URL; per-signal paths (`/v1/traces`, `/v1/metrics`, `/v1/logs`) are appended automatically. |
| `OTEL_EXPORTER_OTLP_HEADERS` | `Authorization=Basic%20dXNlcjpwYXNz` | Shared auth header (percent-encoded). |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | Default. Also accepts `http/json`. `grpc` requires `--features otel-grpc`. |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | `http://traces:4318/v1/traces` | Signal-specific override (used verbatim, no path appending). |

Architecture: our `consent`, `sampling`, `backpressure`, and `resilience`
modules stay in front as pre-filters. The OTel SDK sits behind them and
handles only batching + OTLP network export. When OTel is not configured
or the feature is off, the crate falls back gracefully to in-process
instrumentation.

## Runtime Introspection

Use `get_runtime_config()` to inspect the applied config snapshot and
`get_runtime_status()` to inspect setup state, provider installation, fallback
mode, and the last setup error:

```rust
use provide_telemetry::{get_runtime_config, get_runtime_status};

let cfg = get_runtime_config();
let status = get_runtime_status();

println!("{cfg:?}");
println!("{status:?}");
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

The example suite covers the same numbered telemetry topics as
Python and TypeScript, includes OpenObserve integration examples,
and keeps the OTLP E2E client/server pair used by the cross-language
verification flow.
