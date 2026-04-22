# Go Examples

SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc

Run any example from the repo root:

```bash
cd go && go run ./examples/telemetry/01_basic_telemetry
```

Examples that export to OTLP or OpenObserve import the optional
`github.com/provide-io/provide-telemetry/go/otel` module for side-effect
backend registration.

Run those examples from the optional backend module path:

```bash
cd go && go run ./otel/examples/openobserve/01_emit_all_signals
```

## Telemetry

- **`01_basic_telemetry`** — logging, tracing, and all three metric types (counter, gauge, histogram).
- **`02_w3c_propagation`** — W3C trace-context propagation via `net/http` request headers.
- **`03_sampling_and_backpressure`** — per-signal sampling policies and bounded backpressure queue controls.
- **`04_runtime_reconfigure`** — hot-swap sampling/exporter policies at runtime without restart.
- **`05_pii_and_cardinality_policy`** — PII masking rules (`redact`, `hash`, `drop`) and cardinality guardrails.
- **`06_exporter_resilience_modes`** — retries, timeouts, circuit breaker, and fail-open/fail-closed policies.
- **`07_slo_and_health_snapshot`** — RED/USE SLO metric helpers and full 25-field health snapshot inspection.
- **`08_full_hardening_profile`** — all guardrails active simultaneously: PII, cardinality, backpressure, resilience.
- **`09_error_handling_and_degradation`** — structured error hierarchy and graceful no-OTel degradation.
- **`10_performance_metrics`** — benchmark key telemetry operations (setup, log emit, span start).
- **`11_lazy_loading_proof`** — optional OTel wiring with graceful degradation to no-op when SDK absent.
- **`12_error_fingerprint_and_sessions`** — SHA-256 error fingerprinting and session correlation across spans.
- **`13_security_hardening`** — input sanitization, secret detection, and W3C protocol size guards.
- **`14_data_governance`** — consent levels, data classification with sensitivity labels, and cryptographic redaction receipts.

## OpenObserve Integration

Requires a running OpenObserve instance. Set env vars before running:

```bash
export OPENOBSERVE_URL=http://localhost:5080/api/default
export OPENOBSERVE_USER=user@example.com
export OPENOBSERVE_PASSWORD=password
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:5080/api/default
```

- **`otel/examples/openobserve/01_emit_all_signals`** — emit logs, traces, and metrics to OpenObserve via OTLP.
- **`otel/examples/openobserve/02_verify_ingestion`** — runs `01_emit_all_signals` and polls OpenObserve to confirm all signals appeared.
- **`otel/examples/openobserve/03_hardening_profile`** — full hardening profile with OTLP export to OpenObserve.
