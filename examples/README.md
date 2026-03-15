# Examples

SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC

## Telemetry

Event naming in examples follows strict `domain.action.status` (exactly 3 segments).
Use `undef.telemetry.event_name(domain, action, status)` when composing names.

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

Environment:

```bash
export OPENOBSERVE_URL=http://localhost:5080/api/default
export OPENOBSERVE_USER=user@example.com
export OPENOBSERVE_PASSWORD=password
export OPENOBSERVE_REQUIRED_SIGNALS=logs
```

Run:

```bash
uv run --group dev --extra otel python examples/openobserve/01_emit_all_signals.py
uv run --group dev --extra otel python examples/openobserve/02_verify_ingestion.py
uv run --group dev --extra otel python examples/openobserve/03_hardening_profile.py
```
