# Examples

## Telemetry

Event naming in examples follows the DA(R)S pattern: 3 segments (domain.action.status) or 4 segments (domain.action.resource.status).
Use `provide.telemetry.event(*segments)` when composing structured events.

- `telemetry/01_basic_telemetry.py`
  - Local console/json logging.
  - Trace decorator usage.
  - Counter/histogram emission.
- `telemetry/02_w3c_propagation_asgi.py`
  - W3C `traceparent`/`tracestate`/`baggage` extraction through `TelemetryMiddleware`.
  - Demonstrates bound log context + active trace context.
- `telemetry/03_sampling_and_backpressure.py`
  - Runtime sampling policies per signal.
  - Trace backpressure with bounded queue + drop accounting snapshot.
- `telemetry/04_runtime_reconfigure.py`
  - In-process runtime config update flow.
  - Demonstrates behavior before/after sampling reconfiguration.
- `telemetry/05_pii_and_cardinality_policy.py`
  - PII rules (`hash`, `truncate`, `drop`) and default redaction.
  - Cardinality guard usage for metric attributes.
- `telemetry/06_exporter_resilience_modes.py`
  - Fail-open vs fail-closed exporter behavior with retries.
  - Health counters for retries/failures.
- `telemetry/07_slo_pack_and_health_snapshot.py`
  - RED/USE helper emissions.
  - Error taxonomy and health snapshot output.
- `telemetry/08_full_hardening_profile.py`
  - Combined hardening: PII, cardinality, sampling, backpressure, resilience, SLO.
- `telemetry/09_error_handling_and_degradation.py`
  - `TelemetryError` / `ConfigurationError` / `EventSchemaError` exception hierarchy.
  - Graceful degradation when OTel is not installed.
  - DEBUG logging to diagnose silent OTel fallbacks.
  - Diagnostic warnings for sampling rate clamping and malformed OTLP headers.
- `telemetry/10_performance_metrics.py`
  - Counter/gauge/histogram usage with circuit breaker recovery.
- `telemetry/11_lazy_loading_proof.py`
  - Demonstrates SLO module lazy-loading via `__getattr__` in `__init__.py`.
- `telemetry/12_error_fingerprint_and_sessions.py`
  - Error fingerprinting and session correlation.
- `telemetry/13_security_hardening.py`
  - Security hardening: input sanitization, secret detection.

Run:

```bash
uv run --group dev --extra otel python examples/telemetry/01_basic_telemetry.py
uv run --group dev --extra otel python examples/telemetry/02_w3c_propagation_asgi.py
uv run --group dev --extra otel python examples/telemetry/03_sampling_and_backpressure.py
uv run --group dev --extra otel python examples/telemetry/04_runtime_reconfigure.py
uv run --group dev --extra otel python examples/telemetry/05_pii_and_cardinality_policy.py
uv run --group dev --extra otel python examples/telemetry/06_exporter_resilience_modes.py
uv run --group dev --extra otel python examples/telemetry/07_slo_pack_and_health_snapshot.py
uv run --group dev --extra otel python examples/telemetry/08_full_hardening_profile.py
uv run --group dev --extra otel python examples/telemetry/09_error_handling_and_degradation.py
uv run --group dev --extra otel python examples/telemetry/10_performance_metrics.py
uv run --group dev --extra otel python examples/telemetry/11_lazy_loading_proof.py
uv run --group dev --extra otel python examples/telemetry/12_error_fingerprint_and_sessions.py
uv run --group dev --extra otel python examples/telemetry/13_security_hardening.py
```

## Rust

- `rust/examples/telemetry_01_basic.rs`
  - Basic Rust lifecycle, guard-based context binding, trace wrapper, and fallback metrics.
- `rust/examples/telemetry_02_w3c_propagation.rs`
  - W3C header extraction, propagation-context binding, nested restore behavior.
- `rust/examples/telemetry_03_sampling_and_backpressure.rs`
  - Sampling policies, queue limits, and dropped-trace accounting.
- `rust/examples/telemetry_04_runtime_reconfigure.rs`
  - Runtime config inspection, hot updates, reconfigure, and env reload.
- `rust/examples/telemetry_05_pii_and_cardinality_policy.rs`
  - PII rule registration and cardinality limit clamping.
- `rust/examples/telemetry_06_exporter_resilience_modes.rs`
  - Fail-open/fail-closed exporter behavior, timeout handling, and circuit state.
- `rust/examples/telemetry_07_slo_and_health_snapshot.rs`
  - Error classification and health snapshot inspection.
- `rust/examples/telemetry_08_full_hardening_profile.rs`
  - Combined hardening knobs using the current Rust API surface.
- `rust/examples/telemetry_09_error_handling_and_degradation.rs`
  - Rust error types and graceful degraded-mode behavior.
- `rust/examples/telemetry_10_performance_metrics.rs`
  - Basic hot-path timing for event construction, counters, and sampling.
- `rust/examples/telemetry_11_lazy_loading_proof.rs`
  - Shows Rust telemetry helpers remain cold until SLO or metrics are first used.
- `rust/examples/telemetry_12_error_fingerprint_and_sessions.rs`
  - Stable error fingerprints plus session context lifecycle.
- `rust/examples/telemetry_13_security_hardening.rs`
  - Secret redaction and nested-payload sanitization.
- `rust/examples/telemetry_14_data_governance.rs`
  - Consent gating, classification labels, and redaction receipts.
- `rust/examples/e2e_cross_language_client.rs`
  - Rust OTLP client example used by the cross-language tracing E2E.
- `rust/examples/e2e_cross_language_server.rs`
  - Rust OTLP server example used by the cross-language tracing E2E.

Run:

```bash
cargo run --manifest-path rust/Cargo.toml --example telemetry_01_basic
cargo run --manifest-path rust/Cargo.toml --example telemetry_02_w3c_propagation
cargo run --manifest-path rust/Cargo.toml --example telemetry_03_sampling_and_backpressure
cargo run --manifest-path rust/Cargo.toml --example telemetry_04_runtime_reconfigure
cargo run --manifest-path rust/Cargo.toml --example telemetry_05_pii_and_cardinality_policy
cargo run --manifest-path rust/Cargo.toml --example telemetry_06_exporter_resilience_modes
cargo run --manifest-path rust/Cargo.toml --example telemetry_07_slo_and_health_snapshot
cargo run --manifest-path rust/Cargo.toml --example telemetry_08_full_hardening_profile
cargo run --manifest-path rust/Cargo.toml --example telemetry_09_error_handling_and_degradation
cargo run --manifest-path rust/Cargo.toml --example telemetry_10_performance_metrics
cargo run --manifest-path rust/Cargo.toml --example telemetry_11_lazy_loading_proof
cargo run --manifest-path rust/Cargo.toml --example telemetry_12_error_fingerprint_and_sessions
cargo run --manifest-path rust/Cargo.toml --example telemetry_13_security_hardening
cargo run --manifest-path rust/Cargo.toml --example telemetry_14_data_governance
cargo run --manifest-path rust/Cargo.toml --features otel --example e2e_cross_language_client
cargo run --manifest-path rust/Cargo.toml --features otel --example e2e_cross_language_server -- --port 18765
```

## OpenObserve

- `openobserve/01_emit_all_signals.py`
  - Emits logs, traces, and metrics via OTLP HTTP exporters.
- `openobserve/02_verify_ingestion.py`
  - Captures pre/post stream document totals from OpenObserve API.
  - Verifies required signals from `OPENOBSERVE_REQUIRED_SIGNALS` (default: `logs`).
  - Set `OPENOBSERVE_REQUIRED_SIGNALS=logs,metrics,traces` when OTel extras are installed.
- `openobserve/03_hardening_profile.py`
  - Uses hardening-focused config profile for sampling/backpressure/resilience/SLO.
  - Emits sanitized logs with W3C-ready tracing and metrics export.
- `rust/examples/openobserve_01_emit_all_signals.rs`
  - Emits Rust OTLP logs, traces, metrics, plus a baseline JSON log to OpenObserve.
- `rust/examples/openobserve_02_verify_ingestion.rs`
  - Captures pre/post ingestion counts from the OpenObserve API and waits for Rust signals to appear.
- `rust/examples/openobserve_03_hardening_profile.rs`
  - Applies Rust hardening policies, exports to OpenObserve, and prints the resulting health snapshot.

Start the full dev stack (Grafana/LGTM + OpenObserve + Traefik gateway):

```bash
sh scripts/start-telemetry-stack.sh
```

Or OpenObserve standalone:

```bash
sh scripts/start-openobserve.sh
```

Environment:

```bash
# Direct (no DNS, no proxy)
export OPENOBSERVE_URL=http://localhost:5080/api/default

# Proxied (requires: sudo sh scripts/setup-provide-test-dns.sh)
# export OPENOBSERVE_URL=http://openobserve.provide.test:5314/api/default

export OPENOBSERVE_USER=admin@provide.test
export OPENOBSERVE_PASSWORD=Complexpass#123
export OPENOBSERVE_REQUIRED_SIGNALS=logs
```

Run:

```bash
uv run --group dev --extra otel python examples/openobserve/01_emit_all_signals.py
uv run --group dev --extra otel python examples/openobserve/02_verify_ingestion.py
uv run --group dev --extra otel python examples/openobserve/03_hardening_profile.py
cargo run --manifest-path rust/Cargo.toml --features otel --example openobserve_01_emit_all_signals
cargo run --manifest-path rust/Cargo.toml --features otel --example openobserve_02_verify_ingestion
cargo run --manifest-path rust/Cargo.toml --features otel --example openobserve_03_hardening_profile
```
