# API Reference

All public symbols are exported from `provide.telemetry`. Import everything from the top-level package:

```python
from provide.telemetry import setup_telemetry, get_logger, trace
```

Rust follows the same top-level contract from `rust/src/lib.rs`, but context-setting APIs return guards so prior state is restored automatically when the guard drops.

## Setup and Lifecycle

### `setup_telemetry(config: TelemetryConfig | None = None) -> TelemetryConfig`

Initialize logging, tracing, and metrics providers. Lock-protected and idempotent — safe to call concurrently. Accepts an optional config; defaults to `TelemetryConfig.from_env()`. Returns the applied config.

> **Per-language signatures:** Python accepts an optional `TelemetryConfig` object.
> TypeScript accepts `Partial<TelemetryConfig>` overrides merged over env config.
> Go reads env vars and accepts functional `SetupOption` arguments.
> Rust reads env vars with no programmatic config argument.
> All four read `PROVIDE_*` / `OTEL_*` environment variables as the primary config source.

### `shutdown_telemetry() -> None`

Flush and tear down all providers and reset runtime policies. This clears the package's local setup state, but real OpenTelemetry process-global providers still cannot be replaced in-process once installed. For provider-changing lifecycle transitions, restart the process and call `setup_telemetry()` with the desired config.

## Runtime Configuration

### `update_runtime_config(overrides: RuntimeOverrides) -> TelemetryConfig`

Apply hot-reloadable runtime overrides only. Cold/provider fields are excluded from `RuntimeOverrides`. Returns the applied runtime snapshot.
Safe logging pipeline settings are rebuilt in-process; provider-changing OTLP log settings are rejected once a global OTel log provider is installed.

### `reload_runtime_from_env() -> TelemetryConfig`

Reload config from environment variables, apply only hot-reloadable fields, warn on cold-field drift, and return the active snapshot.

### `get_runtime_config() -> TelemetryConfig`

Return a defensive copy of the active runtime config.

### `reconfigure_telemetry(config: TelemetryConfig | None = None) -> TelemetryConfig`

Apply hot runtime changes. Raises `RuntimeError` if provider-changing config differs and OTel providers are already installed (requires process restart), including OTLP log-provider changes after the global OTel log provider is live.

## Logging

### `get_logger(name: str | None = None) -> structlog-compatible logger`

Return a structlog-compatible wrapped logger (internally a `_TraceWrapper` around a `FilteringBoundLogger`). Auto-configures on first call if `setup_telemetry()` hasn't been called.

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

## Session Context

### `bind_session_context(session_id: str) -> None`

Bind a session ID to all subsequent telemetry events in the current async context. The session ID is injected into every log record, trace span, and metric attribute until cleared.

### `get_session_id() -> str | None`

Return the current session ID from contextvars, or `None` if no session is bound.

### `clear_session_context() -> None`

Clear the session ID from the current async context.

## Error Fingerprinting

Error events automatically receive an `error_fingerprint` field — a 12-character hex digest derived from the exception type and normalized stack trace. Fingerprints are stable across deploys and process restarts, making them suitable for deduplication and alert grouping.

## Event Schema

### `event(*segments: str) -> Event`

Build a structured event from 3 or 4 segments following the DA(R)S pattern (Domain, Action, Resource, Status). Returns an `Event` — a `str` subclass that behaves as a dot-joined string and exposes typed fields.

Requires exactly 3 or 4 segments. In strict mode (`PROVIDE_TELEMETRY_STRICT_EVENT_NAME=true`), also validates format (lowercase, alphanumeric + hyphens); in non-strict mode (the default), only the segment count is checked.

```python
# 3-segment DAS (domain.action.status)
e = event("auth", "login", "success")    # -> "auth.login.success"
e.domain   # "auth"
e.action   # "login"
e.status   # "success"
e.resource # None

# 4-segment DARS (domain.action.resource.status)
e = event("payment", "subscription", "renewal", "success")
e.domain   # "payment"
e.action   # "subscription"
e.resource # "renewal"
e.status   # "success"
```

### `EventRecord` (TypeScript)

TypeScript equivalent for structured event creation. See the [TypeScript README](../typescript/README.md) for usage.

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
@dataclass(frozen=True, slots=True)
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
@dataclass(frozen=True, slots=True)
class QueuePolicy:
    logs_maxsize: int = 0
    traces_maxsize: int = 0
    metrics_maxsize: int = 0
```

### `set_queue_policy(policy: QueuePolicy) -> None`

Replace the active queue policy.

### `get_queue_policy() -> QueuePolicy`

Return the current queue policy.

## Exporter Resilience Policies

### `ExporterPolicy`

```python
@dataclass(frozen=True, slots=True)
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
@dataclass(frozen=True, slots=True)
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
@dataclass(frozen=True, slots=True)
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

NamedTuple with per-signal counters:

Canonical 25-field layout (8 per signal × 3 signals + 1 global), shared across Python, TypeScript, Go, and Rust:

- `emitted_{logs,traces,metrics}` — events accepted and forwarded
- `dropped_{logs,traces,metrics}` — events dropped by sampling or backpressure
- `export_failures_{logs,traces,metrics}` — failed export attempts
- `retries_{logs,traces,metrics}` — exporter retry count
- `export_latency_ms_{logs,traces,metrics}` — latest export latency in ms
- `async_blocking_risk_{logs,traces,metrics}` — calls where retry/backoff ran inside an event loop
- `circuit_state_{logs,traces,metrics}` — circuit breaker state: `"closed"`, `"open"`, or `"half_open"`
- `circuit_open_count_{logs,traces,metrics}` — number of times circuit has opened
- `setup_error` — error message from `setup_telemetry()`, or `None`

### `get_health_snapshot() -> HealthSnapshot`

Return a point-in-time snapshot of all health counters. Thread-safe.

## SLO Helpers

### `record_red_metrics(route: str, method: str, status_code: int, duration_ms: float) -> None`

Emit RED (Rate/Error/Duration) metrics for an HTTP request. Always executes when called directly; the `PROVIDE_SLO_ENABLE_RED_METRICS` flag only controls whether `TelemetryMiddleware` calls this automatically.

### `record_use_metrics(resource: str, utilization_percent: int) -> None`

Emit USE (Utilization) metrics for a resource. Always executes when called directly; the `PROVIDE_SLO_ENABLE_USE_METRICS` flag only controls whether `TelemetryMiddleware` calls this automatically.

### `classify_error(exc_name: str, status_code: int | None = None) -> dict[str, str]`

Return `{"error_type": ..., "error_code": ..., "error_name": ...}` classification. Server (500+), client (400-499), or internal.

## Exceptions

### `TelemetryError`

Base exception for all provide.telemetry errors.

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
- **`SecurityConfig`** — secret detection patterns, header size guards, protocol limits

See [Configuration Reference](CONFIGURATION.md) for the environment variables that drive each field.

## Rust Notes

- `bind_context`, `unbind_context`, `clear_context`, `bind_session_context`, `clear_session_context`, `set_trace_context`, and `bind_propagation_context` return guard objects in Rust. Drop restores the previous snapshot.
- `trace` is exposed as a wrapper function in Rust rather than a decorator.
- `get_meter()` returns a fallback meter wrapper in Rust; fallback `counter()`, `gauge()`, and `histogram()` remain callable without OTel setup.
