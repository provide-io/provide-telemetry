# API Reference

All public symbols are exported from `undef.telemetry`. Import everything from the top-level package:

```python
from undef.telemetry import setup_telemetry, get_logger, trace
```

## Setup and Lifecycle

### `setup_telemetry(config: TelemetryConfig | None = None) -> TelemetryConfig`

Initialize logging, tracing, and metrics providers. Lock-protected and idempotent — safe to call concurrently. Accepts an optional config; defaults to `TelemetryConfig.from_env()`. Returns the applied config.

### `shutdown_telemetry() -> None`

Flush and tear down all providers and reset runtime policies. This clears the package's local setup state, but real OpenTelemetry process-global providers still cannot be replaced in-process once installed. For provider-changing lifecycle transitions, restart the process and call `setup_telemetry()` with the desired config.

## Runtime Configuration

### `update_runtime_config(config: TelemetryConfig) -> TelemetryConfig`

Apply a config snapshot to runtime signal policies (sampling, backpressure, exporter). Returns the active runtime snapshot.

### `reload_runtime_from_env() -> TelemetryConfig`

Reload config from environment variables, apply it, and return the active snapshot.

### `get_runtime_config() -> TelemetryConfig`

Return a defensive copy of the active runtime config.

### `reconfigure_telemetry(config: TelemetryConfig | None = None) -> TelemetryConfig`

Apply hot runtime policy changes. Raises `RuntimeError` if provider-changing config differs and OTel providers are already installed (requires process restart).

## Logging

### `get_logger(name: str | None = None) -> BoundLogger`

Return a structlog logger. Auto-configures on first call if `setup_telemetry()` hasn't been called.

### `logger`

Module-level lazy logger instance. Resolves on first attribute access.

### `bind_context(**kwargs: Any) -> None`

Bind key-value pairs into the structlog contextvars context. Available to all subsequent log events in the current async task.

### `unbind_context(*keys: str) -> None`

Remove keys from the structlog contextvars context.

### `clear_context() -> None`

Clear all structlog contextvars context.

## Tracing

### `trace(name: str | None = None) -> Callable`

Decorator that wraps a function in an OTel span. Works on both sync and async functions. Uses the real tracer if available, no-op otherwise.

### `get_tracer(name: str | None = None) -> Tracer`

Return an OTel tracer (or no-op fallback).

### `tracer`

Module-level lazy tracer instance.

### `get_trace_context() -> dict[str, str | None]`

Return the current `{"trace_id": ..., "span_id": ...}` from contextvars.

### `set_trace_context(trace_id: str | None, span_id: str | None) -> None`

Manually set trace/span IDs in contextvars.

## Metrics

### `counter(name: str, description: str | None = None, unit: str | None = None) -> Counter`

Create or retrieve a named counter instrument.

### `gauge(name: str, description: str | None = None, unit: str | None = None) -> Gauge`

Create or retrieve a named gauge instrument.

### `histogram(name: str, description: str | None = None, unit: str | None = None) -> Histogram`

Create or retrieve a named histogram instrument.

### `get_meter(name: str | None = None) -> Meter | None`

Return the active OTel meter if a real meter provider is available; otherwise return `None`. The in-process fallback lives in the `counter()`, `gauge()`, and `histogram()` wrapper APIs.

## Event Schema

### `event_name(*segments: str) -> str`

Build a strict event name from 3-5 validated lowercase segments joined by dots.

```python
event_name("auth", "login", "success")  # -> "auth.login.success"
```

## ASGI Integration

### `TelemetryMiddleware`

ASGI middleware class. Extracts `x-request-id`, `x-session-id`, and W3C trace headers from incoming requests, binds them to contextvars, and clears on response.

### `bind_websocket_context(scope: dict) -> ContextToken`

Bind context fields from a WebSocket ASGI scope. Binds any of `request_id`, `session_id`, `actor_id` found in headers. Returns a `ContextToken` for cleanup — pass it to `clear_websocket_context()`.

### `clear_websocket_context(token: ContextToken) -> None`

Restore logger context to the state before `bind_websocket_context()` was called.

## W3C Propagation

### `extract_w3c_context(scope: dict) -> PropagationContext`

Parse `traceparent`, `tracestate`, and `baggage` headers from an ASGI scope. Returns a `PropagationContext` dataclass. Invalid traceparent values are rejected silently.

### `bind_propagation_context(context: PropagationContext) -> None`

Push propagation fields into structlog context and trace context. Stackable — supports nested bind/clear pairs.

## Sampling Policies

### `SamplingPolicy`

```python
@dataclass(frozen=True)
class SamplingPolicy:
    default_rate: float = 1.0
    overrides: dict[str, float] = field(default_factory=dict)
```

### `set_sampling_policy(signal: str, policy: SamplingPolicy) -> None`

Set the sampling policy for a signal (`"logs"`, `"traces"`, or `"metrics"`). Rates are clamped to 0.0-1.0.

### `get_sampling_policy(signal: str) -> SamplingPolicy`

Return a copy of the current sampling policy for the given signal.

### `should_sample(signal: str, key: str | None = None) -> bool`

Probabilistic sampling check. Uses per-key override rate if `key` matches, else the default rate. Increments drop counter on rejection.

## Backpressure Policies

### `QueuePolicy`

```python
@dataclass(frozen=True)
class QueuePolicy:
    logs_maxsize: int = 0
    traces_maxsize: int = 0
    metrics_maxsize: int = 0
```

### `set_queue_policy(policy: QueuePolicy) -> None`

Replace the active queue policy. Clears all in-flight queues.

### `get_queue_policy() -> QueuePolicy`

Return the current queue policy.

## Exporter Resilience Policies

### `ExporterPolicy`

```python
@dataclass(frozen=True)
class ExporterPolicy:
    retries: int = 0
    backoff_seconds: float = 0.0
    timeout_seconds: float = 10.0
    fail_open: bool = True
    allow_blocking_in_event_loop: bool = False
```

### `set_exporter_policy(signal: str, policy: ExporterPolicy) -> None`

Set the exporter resilience policy for a signal.

### `get_exporter_policy(signal: str) -> ExporterPolicy`

Return the current exporter policy for a signal.

## PII Sanitization

### `PIIRule`

```python
@dataclass(frozen=True)
class PIIRule:
    path: tuple[str, ...]
    mode: MaskMode = "redact"    # "drop" | "redact" | "hash" | "truncate"
    truncate_to: int = 8
```

### `register_pii_rule(rule: PIIRule) -> None`

Append a PII rule to the active rule list.

### `replace_pii_rules(rules: list[PIIRule]) -> None`

Replace all PII rules atomically.

### `get_pii_rules() -> tuple[PIIRule, ...]`

Return the current PII rules as an immutable tuple.

## Cardinality Guards

### `CardinalityLimit`

```python
@dataclass(frozen=True)
class CardinalityLimit:
    max_values: int
    ttl_seconds: float = 300.0
```

### `register_cardinality_limit(key: str, max_values: int, ttl_seconds: float = 300.0) -> None`

Register a cardinality limit for an attribute key. Values beyond `max_values` are replaced with `"__overflow__"`.

### `get_cardinality_limits() -> dict[str, CardinalityLimit]`

Return the current cardinality limits.

### `clear_cardinality_limits() -> None`

Remove all cardinality limits and reset seen-value tracking.

## Health and Self-Observability

### `HealthSnapshot`

Frozen dataclass with per-signal counters:

- `queue_depth_{logs,traces,metrics}` — current backpressure queue depth
- `dropped_{logs,traces,metrics}` — events dropped by sampling or backpressure
- `retries_{logs,traces,metrics}` — exporter retry count
- `async_blocking_risk_{logs,traces,metrics}` — calls where retry/backoff ran inside an event loop
- `export_failures_{logs,traces,metrics}` — failed export attempts
- `exemplar_unsupported_total` — exemplar attachment attempts on unsupported instruments
- `last_error_{logs,traces,metrics}` — most recent error message (or None)
- `last_successful_export_{logs,traces,metrics}` — epoch timestamp of last success (or None)
- `export_latency_ms_{logs,traces,metrics}` — last successful export latency in ms

### `get_health_snapshot() -> HealthSnapshot`

Return a point-in-time snapshot of all health counters. Thread-safe.

## SLO Helpers

### `record_red_metrics(route: str, method: str, status_code: int, duration_ms: float) -> None`

Emit RED (Rate/Error/Duration) metrics for an HTTP request. Only active when `UNDEF_SLO_ENABLE_RED_METRICS=true`.

### `record_use_metrics(resource: str, utilization_percent: int) -> None`

Emit USE (Utilization) metrics for a resource. Only active when `UNDEF_SLO_ENABLE_USE_METRICS=true`.

### `classify_error(exc_name: str, status_code: int | None = None) -> dict[str, str]`

Return `{"error_type": ..., "error_code": ..., "error_name": ...}` classification. Server (500+), client (400-499), or internal.

## Exceptions

### `TelemetryError`

Base exception for all undef telemetry errors.

### `ConfigurationError`

Raised for invalid configuration. Inherits from both `TelemetryError` and `ValueError`.

### `EventSchemaError`

Raised when an event name or required keys violate schema policy. Inherits from both `TelemetryError` and `ValueError`.

## Config Dataclasses

All config models are `@dataclass(slots=True)` and are constructed via `TelemetryConfig.from_env()`:

- **`TelemetryConfig`** — top-level container with nested sub-configs
- **`LoggingConfig`** — log level, format, caller info, sanitization, pretty renderer settings
- **`TracingConfig`** — tracing enabled, sample rate, OTLP endpoint
- **`MetricsConfig`** — metrics enabled, OTLP endpoint
- **`SchemaConfig`** — strict event name, required keys
- **`SamplingConfig`** — per-signal sampling rates
- **`BackpressureConfig`** — per-signal queue max sizes
- **`ExporterPolicyConfig`** — per-signal retries, backoff, timeout, fail-open, async blocking
- **`SLOConfig`** — RED/USE metrics toggles, error taxonomy

See [Configuration Reference](CONFIGURATION.md) for the environment variables that drive each field.
