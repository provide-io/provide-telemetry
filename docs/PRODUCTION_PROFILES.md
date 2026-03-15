# Production Profiles

This page provides copy/paste environment presets for common production modes.
All profiles assume Python 3.11+ and `setup_telemetry()` called at process startup.

## Strict Profile

Use for safety-first services where schema drift and missing fields must fail fast.

```bash
export UNDEF_TELEMETRY_STRICT_SCHEMA=true
export UNDEF_TELEMETRY_STRICT_EVENT_NAME=true
export UNDEF_TELEMETRY_REQUIRED_KEYS=request_id,service,env
export UNDEF_LOG_SANITIZE=true
export UNDEF_TRACE_SAMPLE_RATE=1.0
export UNDEF_METRICS_ENABLED=true
export UNDEF_TRACE_ENABLED=true
```

Behavior:

- Enforces `domain.action.status` event names.
- Enforces required keys on events.
- Keeps full tracing and metrics signal volume.

## Compat Profile

Use for migration windows where legacy event names/fields may still appear.

```bash
export UNDEF_TELEMETRY_STRICT_SCHEMA=false
export UNDEF_TELEMETRY_STRICT_EVENT_NAME=false
export UNDEF_TELEMETRY_REQUIRED_KEYS=
export UNDEF_LOG_SANITIZE=true
export UNDEF_TRACE_SAMPLE_RATE=0.2
export UNDEF_METRICS_ENABLED=true
export UNDEF_TRACE_ENABLED=true
```

Behavior:

- Accepts non-conforming event names.
- Does not fail events for missing required keys.
- Reduces trace volume while preserving visibility.

## High-Throughput Profile

Use for chatty/event-heavy paths where overhead control matters most.

```bash
export UNDEF_TELEMETRY_STRICT_SCHEMA=false
export UNDEF_TELEMETRY_STRICT_EVENT_NAME=true
export UNDEF_LOG_SANITIZE=true
export UNDEF_TRACE_SAMPLE_RATE=0.05
export UNDEF_METRICS_ENABLED=true
export UNDEF_TRACE_ENABLED=true
```

Behavior:

- Keeps event-name hygiene.
- Uses low trace sampling to reduce p99 overhead and exporter pressure.
- Retains metrics and logs for operational baselines.

## OpenObserve Overlay

Add these on top of any profile when shipping to OpenObserve:

```bash
export OPENOBSERVE_URL=http://localhost:5080/api/default
export OPENOBSERVE_USER=user@example.com
export OPENOBSERVE_PASSWORD=password
```

## Runtime Updates

If your process supports runtime policy updates, treat profile changes as an atomic policy swap:

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
export UNDEF_EXPORTER_LOGS_RETRIES=0
export UNDEF_EXPORTER_TRACES_RETRIES=0
export UNDEF_EXPORTER_METRICS_RETRIES=0
export UNDEF_EXPORTER_LOGS_BACKOFF_SECONDS=0.0
export UNDEF_EXPORTER_TRACES_BACKOFF_SECONDS=0.0
export UNDEF_EXPORTER_METRICS_BACKOFF_SECONDS=0.0
```

If you intentionally allow blocking retry behavior inside the event loop, set:
`UNDEF_EXPORTER_*_ALLOW_BLOCKING_EVENT_LOOP=true`.
