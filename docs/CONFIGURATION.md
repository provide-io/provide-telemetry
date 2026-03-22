# Configuration Reference

All runtime configuration is driven by environment variables, parsed via `TelemetryConfig.from_env()`.

## Core

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `UNDEF_TELEMETRY_SERVICE_NAME` | str | `undef-service` | Service identity attached to all signals |
| `UNDEF_TELEMETRY_ENV` | str | `dev` | Deployment environment tag (e.g. `dev`, `staging`, `prod`) |
| `UNDEF_TELEMETRY_VERSION` | str | `0.0.0` | Application version tag |
| `UNDEF_TELEMETRY_STRICT_SCHEMA` | bool | `false` | Master switch: when true, overrides event name strictness to on |

## Event Schema

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `UNDEF_TELEMETRY_STRICT_EVENT_NAME` | bool | `true` | Require 3-5 dot-separated lowercase segments in event names |
| `UNDEF_TELEMETRY_REQUIRED_KEYS` | str | `""` | Comma-separated list of keys every log event must contain |

## Logging

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `UNDEF_LOG_LEVEL` | str | `INFO` | Log level: `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `UNDEF_LOG_FORMAT` | str | `console` | Renderer: `console`, `json`, or `pretty` |
| `UNDEF_LOG_INCLUDE_TIMESTAMP` | bool | `true` | Add ISO-8601 timestamp to each log event |
| `UNDEF_LOG_INCLUDE_CALLER` | bool | `true` | Add filename and line number to each log event |
| `UNDEF_LOG_SANITIZE` | bool | `true` | Enable PII/sensitive field redaction in log output |
| `UNDEF_LOG_CODE_ATTRIBUTES` | bool | `false` | Attach code attributes to OTel log records |
| `UNDEF_LOG_PRETTY_KEY_COLOR` | str | `dim` | ANSI color name for keys in `pretty` format (see named colors below) |
| `UNDEF_LOG_PRETTY_VALUE_COLOR` | str | `""` | ANSI color name for values in `pretty` format (empty = default) |
| `UNDEF_LOG_PRETTY_FIELDS` | str | `""` | Comma-separated field names to display in `pretty` format |
| `UNDEF_LOG_MODULE_LEVELS` | str | `""` | Per-module log level overrides (e.g. `undef.server=DEBUG,asyncio=WARNING`) |

## Tracing

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `UNDEF_TRACE_ENABLED` | bool | `true` | Enable OTel tracing provider (falls back to no-op when false) |
| `UNDEF_TRACE_SAMPLE_RATE` | float | `1.0` | Trace sampling rate (0.0-1.0) |

## Metrics

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `UNDEF_METRICS_ENABLED` | bool | `true` | Enable OTel metrics provider (falls back to in-process when false) |

## OTLP Endpoints and Headers

These follow the [OpenTelemetry specification](https://opentelemetry.io/docs/specs/otel/protocol/exporter/) for environment-based configuration. Per-signal variables take precedence over the shared fallback.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | str | `None` | Shared OTLP endpoint (fallback for all signals) |
| `OTEL_EXPORTER_OTLP_HEADERS` | str | `None` | Shared OTLP headers (fallback for all signals) |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | str | `None` | Per-signal OTLP endpoint for logs |
| `OTEL_EXPORTER_OTLP_LOGS_HEADERS` | str | `None` | Per-signal OTLP headers for logs |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | str | `None` | Per-signal OTLP endpoint for traces |
| `OTEL_EXPORTER_OTLP_TRACES_HEADERS` | str | `None` | Per-signal OTLP headers for traces |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | str | `None` | Per-signal OTLP endpoint for metrics |
| `OTEL_EXPORTER_OTLP_METRICS_HEADERS` | str | `None` | Per-signal OTLP headers for metrics |

## Sampling

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `UNDEF_SAMPLING_LOGS_RATE` | float | `1.0` | Probability (0.0-1.0) of keeping a log event |
| `UNDEF_SAMPLING_TRACES_RATE` | float | `1.0` | Probability (0.0-1.0) of keeping a trace span |
| `UNDEF_SAMPLING_METRICS_RATE` | float | `1.0` | Probability (0.0-1.0) of keeping a metric observation |

## Backpressure

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `UNDEF_BACKPRESSURE_LOGS_MAXSIZE` | int | `0` | Max queued log events (0 = unlimited) |
| `UNDEF_BACKPRESSURE_TRACES_MAXSIZE` | int | `0` | Max queued trace spans (0 = unlimited) |
| `UNDEF_BACKPRESSURE_METRICS_MAXSIZE` | int | `0` | Max queued metric observations (0 = unlimited) |

## Exporter Resilience

Per-signal retry, backoff, timeout, and failure policy. Each variable is prefixed with `UNDEF_EXPORTER_{SIGNAL}_` where `{SIGNAL}` is `LOGS`, `TRACES`, or `METRICS`.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `UNDEF_EXPORTER_LOGS_RETRIES` | int | `0` | Max retry attempts for log export |
| `UNDEF_EXPORTER_TRACES_RETRIES` | int | `0` | Max retry attempts for trace export |
| `UNDEF_EXPORTER_METRICS_RETRIES` | int | `0` | Max retry attempts for metric export |
| `UNDEF_EXPORTER_LOGS_BACKOFF_SECONDS` | float | `0.0` | Delay between retry attempts for logs |
| `UNDEF_EXPORTER_TRACES_BACKOFF_SECONDS` | float | `0.0` | Delay between retry attempts for traces |
| `UNDEF_EXPORTER_METRICS_BACKOFF_SECONDS` | float | `0.0` | Delay between retry attempts for metrics |
| `UNDEF_EXPORTER_LOGS_TIMEOUT_SECONDS` | float | `10.0` | Per-attempt timeout for log export |
| `UNDEF_EXPORTER_TRACES_TIMEOUT_SECONDS` | float | `10.0` | Per-attempt timeout for trace export |
| `UNDEF_EXPORTER_METRICS_TIMEOUT_SECONDS` | float | `10.0` | Per-attempt timeout for metric export |
| `UNDEF_EXPORTER_LOGS_FAIL_OPEN` | bool | `true` | On exhausted retries: true = drop silently, false = raise |
| `UNDEF_EXPORTER_TRACES_FAIL_OPEN` | bool | `true` | On exhausted retries: true = drop silently, false = raise |
| `UNDEF_EXPORTER_METRICS_FAIL_OPEN` | bool | `true` | On exhausted retries: true = drop silently, false = raise |
| `UNDEF_EXPORTER_LOGS_ALLOW_BLOCKING_EVENT_LOOP` | bool | `false` | Allow retries/backoff inside an async event loop for logs |
| `UNDEF_EXPORTER_TRACES_ALLOW_BLOCKING_EVENT_LOOP` | bool | `false` | Allow retries/backoff inside an async event loop for traces |
| `UNDEF_EXPORTER_METRICS_ALLOW_BLOCKING_EVENT_LOOP` | bool | `false` | Allow retries/backoff inside an async event loop for metrics |

## SLO

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `UNDEF_SLO_ENABLE_RED_METRICS` | bool | `false` | Emit RED (Rate/Error/Duration) HTTP metrics |
| `UNDEF_SLO_ENABLE_USE_METRICS` | bool | `false` | Emit USE (Utilization/Saturation/Errors) resource metrics |
| `UNDEF_SLO_INCLUDE_ERROR_TAXONOMY` | bool | `true` | Auto-classify errors into server/client/internal taxonomy |

## OpenObserve (Examples and E2E Only)

These are not parsed by `TelemetryConfig.from_env()` but are used by the example scripts and E2E tests.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `OPENOBSERVE_URL` | str | — | OpenObserve API base URL |
| `OPENOBSERVE_USER` | str | — | OpenObserve basic auth username |
| `OPENOBSERVE_PASSWORD` | str | — | OpenObserve basic auth password |
| `OPENOBSERVE_REQUIRED_SIGNALS` | str | `logs` | Comma-separated signals to verify in E2E tests |

## Parsing Notes

### Boolean Parsing

Boolean environment variables are parsed case-insensitively. The following values are treated as **true**: `1`, `true`, `yes`, `on`. All other values (including empty string) resolve to the field default (usually `false`).

### OTLP Header Format

OTLP header variables use comma-separated `key=value` pairs following the OTel spec:

```
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer%20token123,X-Custom=value"
```

Keys and values are URL-decoded. Malformed pairs (missing `=`) are silently ignored with a warning.
