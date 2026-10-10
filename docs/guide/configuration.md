# Configuration Reference

Runtime configuration is typically driven by environment variables, parsed via
`TelemetryConfig.from_env()` / `ConfigFromEnv()`. Python and TypeScript also
accept in-memory config at setup; Go accepts `WithConfig(*TelemetryConfig)` so
hosts that re-exec or fork need not mutate process environment to configure
telemetry.

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
| `PROVIDE_LOG_OTLP_ENABLED` | bool | `true` | Enable OTLP log export (independent of PROVIDE_TRACE_ENABLED / PROVIDE_METRICS_ENABLED; set false to skip OTLP handler even when OTEL_EXPORTER_OTLP_ENDPOINT is set) |
<!-- END GENERATED CONFIG: logging -->

## Tracing

<!-- BEGIN GENERATED CONFIG: tracing -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROVIDE_TRACE_ENABLED` | bool | `true` | Enable OTel tracing provider (falls back to no-op when false) |
| `PROVIDE_TRACE_SAMPLE_RATE` | float | `1.0` | Trace sampling rate (0.0-1.0) applied to the OTel SDK ParentBased(TraceIdRatioBased) sampler (and facade when no live provider); combined via min() with PROVIDE_SAMPLING_TRACES_RATE |
<!-- END GENERATED CONFIG: tracing -->

## Metrics

<!-- BEGIN GENERATED CONFIG: metrics -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROVIDE_METRICS_ENABLED` | bool | `true` | Enable OTel metrics provider (falls back to in-process when false) |
| `OTEL_METRICS_EXPORTER` | str | `otlp` | Comma-separated metric exporters: otlp, prometheus, none. prometheus attaches the pull reader. |
| `OTEL_EXPORTER_PROMETHEUS_HOST` | str | `127.0.0.1` | Tier 3 bind host. Loopback by default (the OTel spec says localhost); a non-loopback value logs one warning at setup. |
| `OTEL_EXPORTER_PROMETHEUS_PORT` | int | `9464` | Tier 3 bind port. |
| `PROVIDE_METRICS_PROMETHEUS_LISTEN` | str | `false` | Start the Tier 3 listener: false, true, or auto (start it whenever prometheus is in OTEL_METRICS_EXPORTER). |
| `PROVIDE_METRICS_PROMETHEUS_PATH` | str | `/metrics` | Tier 3 path. Ignored by Tier 2, where the host picks the mount path. |
| `PROVIDE_METRICS_PROMETHEUS_TRANSLATION` | str | `UnderscoreEscapingWithSuffixes` | Metric and label name translation strategy; one of translation.strategies. |
| `PROVIDE_METRICS_PROMETHEUS_SCOPE_LABELS` | bool | `false` | Add otel_scope_name / otel_scope_version labels to every series. |
| `PROVIDE_METRICS_PROMETHEUS_TARGET_INFO` | bool | `true` | Emit the target_info series carrying resource attributes. |
| `PROVIDE_METRICS_HEALTH_OTLP` | bool | `false` | Also export the health metrics over OTLP as observable instruments. |
| `PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG` | str | `""` | Path to a Prometheus web config file (the --web.config.file format) enabling TLS and/or basic auth on the Tier 3 listener. Empty means plain HTTP, no auth. |
<!-- END GENERATED CONFIG: metrics -->

## OTLP Endpoints and Headers

These follow the [OpenTelemetry
specification](https://opentelemetry.io/docs/specs/otel/protocol/exporter/) for
environment-based configuration. Per-signal variables take precedence over the
shared fallback.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
<!-- BEGIN GENERATED CONFIG: otlp -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | str | `""` | Shared OTLP endpoint (fallback for all signals) |
| `OTEL_EXPORTER_OTLP_HEADERS` | str | `""` | Shared OTLP headers (fallback for all signals) |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | str | `""` | Per-signal OTLP endpoint for logs |
| `OTEL_EXPORTER_OTLP_LOGS_HEADERS` | str | `""` | Per-signal OTLP headers for logs |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | str | `""` | Per-signal OTLP endpoint for traces |
| `OTEL_EXPORTER_OTLP_TRACES_HEADERS` | str | `""` | Per-signal OTLP headers for traces |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | str | `""` | Per-signal OTLP endpoint for metrics |
| `OTEL_EXPORTER_OTLP_METRICS_HEADERS` | str | `""` | Per-signal OTLP headers for metrics |
<!-- END GENERATED CONFIG: otlp -->

## Sampling

<!-- BEGIN GENERATED CONFIG: sampling -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROVIDE_SAMPLING_LOGS_RATE` | float | `1.0` | Probability (0.0-1.0) of keeping a log event |
| `PROVIDE_SAMPLING_TRACES_RATE` | float | `1.0` | Probability (0.0-1.0) of keeping a trace span; combined via min() with PROVIDE_TRACE_SAMPLE_RATE and applied to the OTel SDK sampler (global tracer, instrumentations, facade) |
| `PROVIDE_SAMPLING_METRICS_RATE` | float | `1.0` | Probability (0.0-1.0) of keeping a metric observation |
<!-- END GENERATED CONFIG: sampling -->

### Trace sampling semantics

The effective traces rate is `min(PROVIDE_SAMPLING_TRACES_RATE,
PROVIDE_TRACE_SAMPLE_RATE)`. When a live OTel `TracerProvider` is installed,
that rate is applied as `ParentBased(TraceIdRatioBased(rate))` on the SDK
provider — so the global tracer, auto-instrumentation (e.g. gRPC), and the
library facade share one sampling authority. Rate `0` drops root spans; rate `1`
samples all.

When no live provider is installed (noop path), the same rate gates the facade
`should_sample` / `ShouldSample` path only. Changing the sample rate after a
real provider is installed requires process restart (OTel global provider
limits), not in-process hot-reload.

## Backpressure

<!-- BEGIN GENERATED CONFIG: backpressure -->
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROVIDE_BACKPRESSURE_LOGS_MAXSIZE` | int | `0` | Max queued log events (0 = unlimited) |
| `PROVIDE_BACKPRESSURE_TRACES_MAXSIZE` | int | `0` | Max queued trace spans (0 = unlimited) |
| `PROVIDE_BACKPRESSURE_METRICS_MAXSIZE` | int | `0` | Max queued metric observations (0 = unlimited) |
<!-- END GENERATED CONFIG: backpressure -->

## Exporter Resilience

Per-signal retry, backoff, timeout, and failure policy. Each variable is
prefixed with `PROVIDE_EXPORTER_{SIGNAL}_` where `{SIGNAL}` is `LOGS`, `TRACES`,
or `METRICS`.

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
| `PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS` | float | `5.0` | Hard deadline for shutdown_logging() flush+shutdown — prevents process-exit hangs when the logs OTLP endpoint is unreachable; remaining records are dropped if exceeded |
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

## Consent

Read by the consent subsystem, not parsed by `TelemetryConfig.from_env()` — so
it does not appear in the generated tables above and is not part of the
config-parity contract. Every SDK reads it at the same two points: explicit
setup (`setup_telemetry()` / `setupTelemetry()` / `SetupTelemetry()`) and the
lazy logger path taken when a logger is requested before setup. A process that
never calls setup still honours the variable on its first `get_logger()`.

Precedence: the environment wins at setup time over a level set in code before
it; a `set_consent_level()` call made *after* setup is never overwritten (the
lazy path only runs while setup has not happened).

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROVIDE_CONSENT_LEVEL` | str | `FULL` | Consent gate for telemetry collection: `FULL`, `FUNCTIONAL`, `MINIMAL`, or `NONE`. Parsed case-insensitively after trimming whitespace. Unset or blank (empty / whitespace-only) is a no-op — a level chosen in code survives setup. Any other value fails closed: consent becomes `NONE` and a warning naming the value is emitted once per process (Python `RuntimeWarning`, TypeScript `console.warn`, Go/Rust/C# stderr), so a misspelled opt-out stops collection rather than silently leaving it at `FULL`. Read at `setup_telemetry()` and on the first `get_logger()` before setup; a `set_consent_level()` made after setup is never overwritten by it. |

## OpenObserve (Examples and E2E Only)

These are not parsed by `TelemetryConfig.from_env()` but are used by the example
scripts and E2E tests.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `OPENOBSERVE_URL` | str | — | OpenObserve API base URL |
| `OPENOBSERVE_USER` | str | — | OpenObserve basic auth username |
| `OPENOBSERVE_PASSWORD` | str | — | OpenObserve basic auth password |
| `OPENOBSERVE_REQUIRED_SIGNALS` | str | `logs` | Comma-separated signals to verify in E2E tests |

## Sending Metrics to Prometheus

Prometheus 3 accepts OTLP directly, so the ordinary OTLP metrics exporter works
with it in every SDK; no Prometheus-specific setting is needed. Start
Prometheus with `--web.enable-otlp-receiver` (the `prometheus` service in
`docker-compose.yml` does) and point the metrics endpoint at it:

```bash
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=http://localhost:9090/api/v1/otlp/v1/metrics
# or, with the shared endpoint, the SDK appends /v1/metrics itself:
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:9090/api/v1/otlp
```

What to expect on the Prometheus side:

- `job` is the service name and `instance` is `service.instance.id`. Other
  resource attributes land on the `target_info` series unless they are listed
  under `otlp.promote_resource_attributes` (see `infra/prometheus/prometheus.yml`).
- Names are translated by Prometheus according to `otlp.translation_strategy`.
  With the default, `UnderscoreEscapingWithSuffixes`, dots become underscores,
  counters gain `_total` and units become suffixes: a histogram
  `http.request.duration` with unit `ms` is stored as
  `http_request_duration_milliseconds_bucket`, `_sum` and `_count`.
- Prometheus rejects delta temporality by default. The SDKs export cumulative
  metrics, which is what it expects.
- Units reach Prometheus from every SDK. In Rust the first
  `counter()`/`gauge()`/`histogram()` to record under a name fixes its unit and
  description until teardown; a later one with the same name and a different
  unit reuses the first instrument rather than exporting a second stream.
  TypeScript gauges are sent as non-monotonic sums, so a gauge with unit `1`
  does not gain `_ratio` there. This is tracked as a
  `known_divergences` entry in `spec/telemetry-api.yaml`.

For a Prometheus that requires TLS or basic auth (its `--web.config.file`),
use the standard OTLP variables:

```bash
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=https://prom.example:9090/api/v1/otlp/v1/metrics
OTEL_EXPORTER_OTLP_METRICS_HEADERS="Authorization=Basic%20<base64 of user:password>"
OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE=/etc/ssl/private-ca.crt   # only for a private CA
```

Python, TypeScript and Go honour all three. Rust ignores the certificate
variables, so it can reach only a server whose certificate the system already
trusts. C# ignores the certificate variables and the per-signal headers
variable; use the shared `OTEL_EXPORTER_OTLP_HEADERS` there. In the cases they
ignore, export fails without an error: check `get_health_snapshot()`.

The `prometheus-push` job in `.github/workflows/ci-contracts.yml` pushes from
all five SDKs to real Prometheus instances (plain, basic auth, and TLS with a
private CA plus basic auth) and checks every series it reads back.

## Serving Metrics for Prometheus to Scrape (Go, Python)

The Go and Python SDKs can also serve metrics for Prometheus to pull. The
other SDKs follow; see `docs/plans/2026-10-10-prometheus-metrics-design.md`.

Add `prometheus` to `OTEL_METRICS_EXPORTER` (`prometheus` alone, or
`otlp,prometheus` to push as well), then either mount the handler on a server
you already run:

```go
import provideotel "github.com/provide-io/provide-telemetry/go/otel"

mux.Handle("/metrics", provideotel.MetricsHandler())
```

```python
from provide.telemetry import metrics_handler

app.mount("/metrics", metrics_handler())  # any ASGI framework; render_prometheus() for others
```

or let the SDK run its own listener with `PROVIDE_METRICS_PROMETHEUS_LISTEN=true`.
It binds `127.0.0.1:9464` and serves `/metrics` unless
`OTEL_EXPORTER_PROMETHEUS_HOST`, `OTEL_EXPORTER_PROMETHEUS_PORT` and
`PROVIDE_METRICS_PROMETHEUS_PATH` say otherwise. To require TLS or basic auth,
point `PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG` at a file in the format
Prometheus itself takes as `--web.config.file` (Python needs the
`provide-telemetry[prometheus]` extra to read it):

```yaml
tls_server_config:
  cert_file: server.crt        # relative paths resolve against this file
  key_file: server.key
  client_ca_file: clients.crt  # optional: require client certificates
  min_version: TLS12           # or TLS13
basic_auth_users:
  scraper: $2a$10$...          # bcrypt hash, e.g. htpasswd -nBC 10 scraper
```

Only those keys are accepted. If the file or a certificate it names has a
problem, the listener does not start (it never falls back to plain HTTP); the
reason is logged (`otel.prometheus_listener_failed` in Go,
`metrics.prometheus_listener.failed` in Python) and appears as the health
snapshot's setup error. Certificates are re-read when they change.

The scrape also carries the SDK's own health as `provide_telemetry_*` series
(`provide_telemetry_export_failures_total{signal}`,
`provide_telemetry_circuit_state{signal}` and so on), which stay visible when
OTLP export is failing. Set `PROVIDE_METRICS_HEALTH_OTLP=true` to export the
same series over OTLP as well; a scrape still carries each one once.
Callback-reported values use observable instruments,
whose callbacks run on each scrape: `NewObservableGauge`,
`NewObservableCounter` and `NewObservableUpDownCounter` in Go;
`observable_gauge`, `observable_counter` and `observable_up_down_counter` in
Python, each taking a zero-argument callback that returns `Observation`s and
returning a handle with `unregister()`.

## Resource Attributes

Every emitted trace, metric, and log carries an OTel **Resource** identifying
the service. Three identity attributes are populated from configuration:

| Resource attribute        | Config field / env var                          | Default           |
|---------------------------|-------------------------------------------------|-------------------|
| `service.name`            | `PROVIDE_TELEMETRY_SERVICE_NAME`                | `provide-service` |
| `deployment.environment`  | `PROVIDE_TELEMETRY_ENV`                          | `dev`             |
| `service.version`         | `PROVIDE_TELEMETRY_VERSION`                      | `0.0.0`           |

The standard OTel resource env vars — `OTEL_SERVICE_NAME` and
`OTEL_RESOURCE_ATTRIBUTES` (e.g.
`host.name=web-1,service.instance.id=abc,k8s.pod.name=…`) — are also honored, so
deployment/ops can attach attributes without a custom provider.

### Precedence

Identity attributes resolve on a single ladder, lowest to highest:

```
framework default  <  OTEL_* env  <  explicit config
```

- **Explicit config wins.** An identity attribute is treated as *explicitly set*
  only when its configured value differs from the framework default. Such a
  value overrides any `OTEL_*` env value, so an app that names itself `checkout`
  is never silently renamed by an ambient `OTEL_RESOURCE_ATTRIBUTES` injected by
  a platform.
- **Env fills the unset.** If an identity attribute is left at its default,
  `OTEL_SERVICE_NAME` / `OTEL_RESOURCE_ATTRIBUTES` fills it.
- **Additive env keys always merge.** Non-identity keys (`host.name`,
  `service.instance.id`, `k8s.*`, …) are always attached.

This ladder is identical across Python, TypeScript, Go, Rust, and C# — all five
emit the same attribute keys (`service.name`, `deployment.environment`,
`service.version`) — and the shared `resource_precedence` contract in
`spec/behavioral_fixtures.yaml` pins the "explicit = differs from default" gate
that every implementation applies. C#'s builder is
`csharp/src/Provide.Telemetry/ResourceBuilder.cs`, and its
`ResourcePrecedence_ServiceNameFromEnv` test is the C# entry for the
`resource_precedence` category in `spec/fixture_test_ids.yaml`.

## Parsing Notes

### Boolean Parsing

Boolean environment variables are parsed case-insensitively. The following
values are treated as **true**: `1`, `true`, `yes`, `on`. The following values
are treated as **false**: `0`, `false`, `no`, `off`. Empty or whitespace-only
values resolve to the field default. Any other non-empty value is rejected as
invalid configuration.

### OTLP Header Format

OTLP header variables use comma-separated `key=value` pairs following the OTel
spec:

```
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer%20token123,X-Custom=value"
```

Keys and values are URL-decoded. Malformed pairs (missing `=`) are silently
ignored with a warning.
