# Provide.Telemetry (C#)

Idiomatic C# implementation of provide-telemetry at API parity with Python, TypeScript, Go, and Rust.

## Packages

| Package | Dependencies | What it gives you |
| --- | --- | --- |
| `Provide.Telemetry` | BCL only | The whole facade: logging, tracing, metrics, governance, health. Signals render locally. |
| `Provide.Telemetry.OpenTelemetry` | `Provide.Telemetry` + OpenTelemetry + `Microsoft.Extensions.*` + YamlDotNet + BCrypt.Net-Next | OTLP delivery for all three signals, and the Prometheus pull handler and listener. |

The core package has no exporter dependency, so an application that does not want
OpenTelemetry on its dependency graph installs it alone and every call still works.
To export, add the integration package and register it once, before setup:

```csharp
using Provide.Telemetry.OpenTelemetry;

OpenTelemetryBackendRegistration.Register();
```

Nothing else about the application changes — see `consumer/Provide.Telemetry.CoreConsumer`
and `consumer/Provide.Telemetry.OpenTelemetryConsumer` for the same program either way.

## Requirements

- .NET 10 SDK
- Optional: OpenObserve credentials for live OTLP integration tests

## Build & test

```bash
dotnet build csharp/Provide.Telemetry.sln
dotnet test csharp/Provide.Telemetry.sln --nologo
```

## Usage

```csharp
using Provide.Telemetry;

var cfg = ProvideTelemetry.SetupTelemetry();
var log = ProvideTelemetry.GetLogger("app");
log.Info("user.auth.success");
ProvideTelemetry.Counter("requests").Add(1);
using var span = ProvideTelemetry.GetTracer().StartSpan("work");
ProvideTelemetry.FlushTelemetry();
ProvideTelemetry.ShutdownTelemetry();
```

Configuration is env-driven (`PROVIDE_*` / `OTEL_*`), matching the polyglot contract;
see [`docs/guide/configuration.md`](../docs/guide/configuration.md).

### Metrics

`Counter`, `Gauge` and `Histogram` take an optional description and unit:

```csharp
ProvideTelemetry.Histogram("http.request.duration", "Request latency", "ms").Record(14.2);
```

Observable instruments report through a callback that runs at each collection
(every Prometheus scrape, every OTLP export interval). Create them after setup;
without a provider the callback never runs.

```csharp
var depth = ProvideTelemetry.ObservableGauge("queue.depth",
    () => [new Observation(queue.Count)]);
// ... later ...
depth.Unregister();
```

`ObservableCounter` and `ObservableUpDownCounter` take the same arguments.

### Prometheus

With the integration package registered, add `prometheus` to
`OTEL_METRICS_EXPORTER` (`prometheus` alone, or `otlp,prometheus` to push as
well). `PrometheusMetrics.MetricsHandler(method, accept)` is framework-neutral:
copy its status, headers and body onto your server's response.

```csharp
using Provide.Telemetry.OpenTelemetry;

app.MapMethods("/metrics", ["GET", "HEAD"], (HttpContext ctx) =>
{
    var r = PrometheusMetrics.MetricsHandler(ctx.Request.Method, ctx.Request.Headers.Accept);
    foreach (var (name, value) in r.Headers) ctx.Response.Headers[name] = value;
    ctx.Response.StatusCode = r.Status;
    return ctx.Response.Body.WriteAsync(r.Body).AsTask();
});
```

It answers 405 to methods other than GET and HEAD, and 503 with a one-line
reason before setup, after shutdown, with metrics disabled, or without the
Prometheus reader. `PrometheusMetrics.RenderPrometheus(accept)` returns just
the body and content type, and throws `TelemetryError` naming the reason when
there is nothing to serve.

`PROVIDE_METRICS_PROMETHEUS_LISTEN=true` (or `auto`) starts a standalone
listener on `127.0.0.1:9464/metrics` instead (`OTEL_EXPORTER_PROMETHEUS_HOST`,
`OTEL_EXPORTER_PROMETHEUS_PORT`, `PROVIDE_METRICS_PROMETHEUS_PATH`), with TLS
and basic auth from `PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG`. A listener that
cannot start logs `metrics.prometheus_listener.failed` and sets the health
snapshot's setup error; setup still succeeds. Every scrape also carries the
SDK's own health as `provide_telemetry_*` series, and
`PROVIDE_METRICS_HEALTH_OTLP=true` exports them over OTLP as well.

### OTLP over TLS

`OTEL_EXPORTER_OTLP_CERTIFICATE`, `_CLIENT_CERTIFICATE` and `_CLIENT_KEY`
(each with per-signal `OTEL_EXPORTER_OTLP_{LOGS,TRACES,METRICS}_*` forms that
win) configure the CA and mutual TLS. A file that cannot be read or loaded
leaves that signal's exporter unbuilt, logs `otlp.tls_file_unreadable` and sets
the health snapshot's setup error; setup still succeeds and the other signals
are unaffected.

### Health and reserved fields

A log record counts as emitted once the local sink and the backend have run,
even when the backend throws (that also counts as an export failure). One
refused before export — by consent, sampling or backpressure — counts as
dropped instead, never as both.

The SDK stamps the service identity and, while a span is live, the trace and
span IDs on every record. A caller attribute under one of those names
(`service`, `env`, `version`, `trace_id`, `span_id`, or C#'s `service_name`
and `environment`) is replaced by the stamped value rather than duplicated; to
name a remote service, use `peer.service`.

### Event names

`Schema.Event()` accepts exactly 3 segments (`domain.action.status`) or 4
(`domain.action.resource.status`). That count is a property of the record shape,
so it applies in every mode.

`Schema.EventName()` and `Schema.ValidateEventName()` follow the shared
five-language name contract instead, which depends on the schema mode:

- **Relaxed** (the default) accepts one or more segments and enforces no segment
  grammar, so `Schema.EventName("startup")` and
  `Schema.EventName("User", "Login-OK")` are both valid.
- **Strict** (`PROVIDE_TELEMETRY_STRICT_SCHEMA=true`) accepts 3-5 segments, each
  matching `^[a-z][a-z0-9_]*$`.
- Zero segments and empty segments throw in both modes, so
  `Schema.EventName()`, `Schema.EventName("user", "", "ok")` and
  `Schema.ValidateEventName("a..b")` all raise `EventSchemaError`.

## Examples

See [`examples/README.md`](examples/README.md) for runnable demos:

```bash
dotnet run --project csharp/examples/telemetry/01_basic_telemetry
dotnet run --project csharp/examples/telemetry/02_w3c_propagation
# requires OPENOBSERVE_* :
dotnet run --project csharp/examples/openobserve/01_emit_all_signals
```
