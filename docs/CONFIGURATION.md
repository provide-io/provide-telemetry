# Configuration Reference

All runtime configuration is driven by environment variables, parsed via `TelemetryConfig.from_env()`.

## Core

<!-- BEGIN GENERATED CONFIG: core -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROVIDE_TELEMETRY_SERVICE_NAME` | str | `provide-service` | Service identity attached to all signals |
| `PROVIDE_TELEMETRY_ENV` | str | `dev` | Deployment environment tag (e.g. dev, staging, prod) |
| `PROVIDE_TELEMETRY_VERSION` | str | `0.0.0` | Application version tag |
| `PROVIDE_TELEMETRY_STRICT_SCHEMA` | bool | `false` | Master switch: when true, overrides event name strictness to on |
<!-- END GENERATED CONFIG: core -->

## Event Schema

<!-- BEGIN GENERATED CONFIG: event_schema -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROVIDE_TELEMETRY_STRICT_EVENT_NAME` | bool | `false` | Require 3-5 dot-separated lowercase segments in event names |
| `PROVIDE_TELEMETRY_REQUIRED_KEYS` | str | `""` | Comma-separated list of keys every log event must contain |
<!-- END GENERATED CONFIG: event_schema -->

## Logging

<!-- BEGIN GENERATED CONFIG: logging -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROVIDE_LOG_LEVEL` | str | `INFO` | Log level: TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `PROVIDE_LOG_FORMAT` | str | `console` | Renderer: console, json, or pretty |
| `PROVIDE_LOG_INCLUDE_TIMESTAMP` | bool | `true` | Add ISO-8601 timestamp to each log event |
| `PROVIDE_LOG_INCLUDE_CALLER` | bool | `true` | Add filename and line number to each log event |
| `PROVIDE_LOG_SANITIZE` | bool | `true` | Enable PII/sensitive field redaction in log output |
| `PROVIDE_LOG_PII_MAX_DEPTH` | int | `8` | Maximum nesting depth for PII/sensitive field traversal during sanitization |
| `PROVIDE_LOG_CODE_ATTRIBUTES` | bool | `false` | Attach code attributes to OTel log records |
| `PROVIDE_LOG_PRETTY_KEY_COLOR` | str | `dim` | ANSI color name for keys in pretty format (see named colors below) |
| `PROVIDE_LOG_PRETTY_VALUE_COLOR` | str | `""` | ANSI color name for values in pretty format (empty = default) |
| `PROVIDE_LOG_PRETTY_FIELDS` | str | `""` | Comma-separated field names to display in pretty format |
| `PROVIDE_LOG_MODULE_LEVELS` | str | `""` | Per-module log level overrides (e.g. provide.server=DEBUG,asyncio=WARNING) |
<!-- END GENERATED CONFIG: logging -->

## Tracing

<!-- BEGIN GENERATED CONFIG: tracing -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROVIDE_TRACE_ENABLED` | bool | `true` | Enable OTel tracing provider (falls back to no-op when false) |
| `PROVIDE_TRACE_SAMPLE_RATE` | float | `1.0` | Trace sampling rate (0.0-1.0) |
<!-- END GENERATED CONFIG: tracing -->

## Metrics

<!-- BEGIN GENERATED CONFIG: metrics -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROVIDE_METRICS_ENABLED` | bool | `true` | Enable OTel metrics provider (falls back to in-process when false) |
<!-- END GENERATED CONFIG: metrics -->

## OTLP Endpoints and Headers

These follow the [OpenTelemetry specification](https://opentelemetry.io/docs/specs/otel/protocol/exporter/) for environment-based configuration. Per-signal variables take precedence over the shared fallback.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
<!-- BEGIN GENERATED CONFIG: otlp -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | str | None | Shared OTLP endpoint (fallback for all signals) |
| `OTEL_EXPORTER_OTLP_HEADERS` | str | None | Shared OTLP headers (fallback for all signals) |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | str | None | Per-signal OTLP endpoint for logs |
| `OTEL_EXPORTER_OTLP_LOGS_HEADERS` | str | None | Per-signal OTLP headers for logs |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | str | None | Per-signal OTLP endpoint for traces |
| `OTEL_EXPORTER_OTLP_TRACES_HEADERS` | str | None | Per-signal OTLP headers for traces |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | str | None | Per-signal OTLP endpoint for metrics |
| `OTEL_EXPORTER_OTLP_METRICS_HEADERS` | str | None | Per-signal OTLP headers for metrics |
<!-- END GENERATED CONFIG: otlp -->

## Sampling

<!-- BEGIN GENERATED CONFIG: sampling -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROVIDE_SAMPLING_LOGS_RATE` | float | `1.0` | Probability (0.0-1.0) of keeping a log event |
| `PROVIDE_SAMPLING_TRACES_RATE` | float | `1.0` | Probability (0.0-1.0) of keeping a trace span |
| `PROVIDE_SAMPLING_METRICS_RATE` | float | `1.0` | Probability (0.0-1.0) of keeping a metric observation |
<!-- END GENERATED CONFIG: sampling -->

## Backpressure

<!-- BEGIN GENERATED CONFIG: backpressure -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROVIDE_BACKPRESSURE_LOGS_MAXSIZE` | int | `0` | Max queued log events (0 = unlimited) |
| `PROVIDE_BACKPRESSURE_TRACES_MAXSIZE` | int | `0` | Max queued trace spans (0 = unlimited) |
| `PROVIDE_BACKPRESSURE_METRICS_MAXSIZE` | int | `0` | Max queued metric observations (0 = unlimited) |
<!-- END GENERATED CONFIG: backpressure -->

## Exporter Resilience

Per-signal retry, backoff, timeout, and failure policy. Each variable is prefixed with `PROVIDE_EXPORTER_{SIGNAL}_` where `{SIGNAL}` is `LOGS`, `TRACES`, or `METRICS`.

<!-- BEGIN GENERATED CONFIG: exporter -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROVIDE_EXPORTER_LOGS_RETRIES` | int | `0` | Max retry attempts for log export |
| `PROVIDE_EXPORTER_TRACES_RETRIES` | int | `0` | Max retry attempts for trace export |
| `PROVIDE_EXPORTER_METRICS_RETRIES` | int | `0` | Max retry attempts for metric export |
| `PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS` | float | `0.0` | Delay between retry attempts for logs |
| `PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS` | float | `0.0` | Delay between retry attempts for traces |
| `PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS` | float | `0.0` | Delay between retry attempts for metrics |
| `PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS` | float | `10.0` | Per-attempt timeout for log export |
| `PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS` | float | `10.0` | Per-attempt timeout for trace export |
| `PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS` | float | `10.0` | Per-attempt timeout for metric export |
| `PROVIDE_EXPORTER_LOGS_FAIL_OPEN` | bool | `true` | On exhausted retries: true = drop silently, false = raise |
| `PROVIDE_EXPORTER_TRACES_FAIL_OPEN` | bool | `true` | On exhausted retries: true = drop silently, false = raise |
| `PROVIDE_EXPORTER_METRICS_FAIL_OPEN` | bool | `true` | On exhausted retries: true = drop silently, false = raise |
| `PROVIDE_EXPORTER_LOGS_ALLOW_BLOCKING_EVENT_LOOP` | bool | `false` | Allow retries/backoff inside an async event loop for logs |
| `PROVIDE_EXPORTER_TRACES_ALLOW_BLOCKING_EVENT_LOOP` | bool | `false` | Allow retries/backoff inside an async event loop for traces |
| `PROVIDE_EXPORTER_METRICS_ALLOW_BLOCKING_EVENT_LOOP` | bool | `false` | Allow retries/backoff inside an async event loop for metrics |
<!-- END GENERATED CONFIG: exporter -->

## SLO

<!-- BEGIN GENERATED CONFIG: slo -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROVIDE_SLO_ENABLE_RED_METRICS` | bool | `false` | Emit RED (Rate/Error/Duration) HTTP metrics |
| `PROVIDE_SLO_ENABLE_USE_METRICS` | bool | `false` | Emit USE (Utilization/Saturation/Errors) resource metrics |
| `PROVIDE_SLO_INCLUDE_ERROR_TAXONOMY` | bool | `true` | Auto-classify errors into server/client/internal taxonomy |
<!-- END GENERATED CONFIG: slo -->

## Security

<!-- BEGIN GENERATED CONFIG: security -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH` | int | `1024` | Maximum string length for log attribute values (truncated beyond this) |
| `PROVIDE_SECURITY_MAX_ATTR_COUNT` | int | `64` | Maximum number of attributes per log event (excess keys dropped) |
| `PROVIDE_SECURITY_MAX_NESTING_DEPTH` | int | `8` | Maximum nesting depth for dict/list attribute values |
<!-- END GENERATED CONFIG: security -->

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

Boolean environment variables are parsed case-insensitively. The following values are treated as **true**: `1`, `true`, `yes`, `on`. The following values are treated as **false**: `0`, `false`, `no`, `off`. Empty or whitespace-only values resolve to the field default. Any other non-empty value is rejected as invalid configuration.

### OTLP Header Format

OTLP header variables use comma-separated `key=value` pairs following the OTel spec:

```
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer%20token123,X-Custom=value"
```

Keys and values are URL-decoded. Malformed pairs (missing `=`) are silently ignored with a warning.
