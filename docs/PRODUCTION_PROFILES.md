# Production Profiles

This page provides copy/paste environment presets for common production modes.
All profiles assume Python 3.11+ and `setup_telemetry()` called at process startup.

## Strict Profile

Use for safety-first services where schema drift and missing fields must fail fast.

```bash
export PROVIDE_TELEMETRY_STRICT_SCHEMA=true
export PROVIDE_TELEMETRY_STRICT_EVENT_NAME=true
export PROVIDE_TELEMETRY_REQUIRED_KEYS=request_id,service,env
export PROVIDE_LOG_SANITIZE=true
export PROVIDE_TRACE_SAMPLE_RATE=1.0
export PROVIDE_METRICS_ENABLED=true
export PROVIDE_TRACE_ENABLED=true
```

Behavior:

- Enforces 3-5 segment event names.
- Enforces required keys on events.
- Keeps full tracing and metrics signal volume.

## Compat Profile

Use for migration windows where legacy event names/fields may still appear.

```bash
export PROVIDE_TELEMETRY_STRICT_SCHEMA=false
export PROVIDE_TELEMETRY_STRICT_EVENT_NAME=false
export PROVIDE_TELEMETRY_REQUIRED_KEYS=
export PROVIDE_LOG_SANITIZE=true
export PROVIDE_TRACE_SAMPLE_RATE=0.2
export PROVIDE_METRICS_ENABLED=true
export PROVIDE_TRACE_ENABLED=true
```

Behavior:

- Accepts non-conforming event names.
- Does not fail events for missing required keys.
- Reduces trace volume while preserving visibility.

## High-Throughput Profile

Use for chatty/event-heavy paths where overhead control matters most.

```bash
export PROVIDE_TELEMETRY_STRICT_SCHEMA=false
export PROVIDE_TELEMETRY_STRICT_EVENT_NAME=true
export PROVIDE_LOG_SANITIZE=true
export PROVIDE_TRACE_SAMPLE_RATE=0.05
export PROVIDE_METRICS_ENABLED=true
export PROVIDE_TRACE_ENABLED=true
```

Behavior:

- Keeps event-name hygiene.
- Uses low trace sampling to reduce p99 overhead and exporter pressure.
- Retains metrics and logs for operational baselines.

## OpenObserve Overlay

Add these on top of any profile when shipping to OpenObserve:

```bash
export OPENOBSERVE_URL=http://localhost:5080/api/default
export OPENOBSERVE_USER=admin@provide.test
export OPENOBSERVE_PASSWORD=Complexpass#123
```

## Runtime Updates

Profile changes involve two mechanisms with different scopes:

**Hot-reconfigurable** (no restart, via `update_runtime_config()`):
sampling policies, backpressure queue limits, exporter retry/timeout policies.

**Requires restart** (process restart; do not rely on `reconfigure_telemetry()` once OTel providers are installed):
log handlers, schema strictness, tracer/meter providers, OTLP endpoints.

Recommended procedure:

1. Call `update_runtime_config()` to adjust sampling and resilience settings.
2. If schema/provider changes are needed, restart the process with the new env/config and call `setup_telemetry()` during startup.
   `reconfigure_telemetry()` only hot-applies runtime policy changes; for provider-changing config after OTel providers are installed it raises `RuntimeError` and tells the caller to restart.
3. Monitor health snapshot counters (drops, retries, export failures).

## Async Exporter Safety

For async web services, keep retries/backoff at zero (the defaults):

```bash
export PROVIDE_EXPORTER_LOGS_RETRIES=0
export PROVIDE_EXPORTER_TRACES_RETRIES=0
export PROVIDE_EXPORTER_METRICS_RETRIES=0
export PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS=0.0
export PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS=0.0
export PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS=0.0
```

If you intentionally allow blocking retry behavior inside the event loop, set:
`PROVIDE_EXPORTER_*_ALLOW_BLOCKING_EVENT_LOOP=true`.
