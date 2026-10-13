# provide-telemetry/go

Structured logging + OpenTelemetry traces and metrics for Go — feature parity
with the [`provide-telemetry`](https://pypi.org/p/provide-telemetry) Python and
TypeScript packages.

## Install

```bash
go get github.com/provide-io/provide-telemetry/go
```

Requires Go 1.26+.

### Optional OTel peer dependencies

To export traces and metrics to an OTLP endpoint (e.g. OpenObserve, Jaeger,
Tempo), add the optional backend module and wire real SDK providers at setup
time:

```bash
go get github.com/provide-io/provide-telemetry/go/otel
```

```go
import (
    telemetry "github.com/provide-io/provide-telemetry/go"
    _ "github.com/provide-io/provide-telemetry/go/otel"
    sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

tp := sdktrace.NewTracerProvider(/* exporters */)
cfg, err := telemetry.SetupTelemetry(telemetry.WithTracerProvider(tp))
```

Importing `github.com/provide-io/provide-telemetry/go/otel` also activates
OTLP environment-variable wiring for `SetupTelemetry()`. Without that optional
module, the core package degrades gracefully to no-op tracers and meters.

## Quick start

```go
package main

import (
    "context"
    "log"

    telemetry "github.com/provide-io/provide-telemetry/go"
)

func main() {
    cfg, err := telemetry.SetupTelemetry()
    if err != nil {
        log.Fatal(err)
    }
    defer telemetry.ShutdownTelemetry(context.Background())

    _ = cfg

    ctx := context.Background()
    logger := telemetry.GetLogger(ctx, "my.service")
    logger.Info("my.service.started.ok")
}
```

## API reference

### Setup

| Export | Description |
|--------|-------------|
| `SetupTelemetry(opts...)` | Idempotent init from env (default) or `WithConfig(cfg)`. Returns `*TelemetryConfig`. |
| `WithConfig(cfg)` | In-memory config; prefer over mutating `os.Environ` for re-exec/fork hosts. |
| `WithLogOutput(w)` | Send rendered log records to `w` instead of `os.Stderr`. `ReconfigureTelemetry` accepts it too; `ShutdownTelemetry` releases it. |
| `FlushTelemetry(ctx)` | Drain every installed provider and leave them installed. Returns the drain error; an expired deadline is not suppressed. |
| `ShutdownTelemetry(ctx)` | Flush and shut down all OTel providers. |
| `ConfigFromEnv()` | Parse environment variables into a `*TelemetryConfig`. |
| `DefaultTelemetryConfig()` | Return a config with all defaults applied. |

### Logging

```go
logger := telemetry.GetLogger(ctx, "api.handler")
logger.Info("request.received.ok", slog.Int("status", 200))
logger.Error("db.query.error", slog.String("table", "users"))
```

Event names follow the DA(R)S pattern: `Event()` accepts exactly 3 segments
(`domain.action.status`) or 4 segments (`domain.action.resource.status`). That
count is a property of the record shape, so it applies in every mode.

`EventName()` and `ValidateEventName()` follow the shared five-language name
contract instead, which depends on the schema mode:

- **Relaxed** (the default) accepts one or more segments and enforces no segment
  grammar, so `EventName("startup")` and `EventName("User", "Login-OK")` are
  both valid.
- **Strict** (`PROVIDE_TELEMETRY_STRICT_SCHEMA=true`) accepts 3–5 segments, each
  matching `^[a-z][a-z0-9_]*$`.
- Zero segments and empty segments fail in both modes, so `EventName()`,
  `EventName("user", "", "ok")` and `ValidateEventName("a..b")` all return an
  error.

#### Callsite through an adapter

With `PROVIDE_LOG_INCLUDE_CALLER` on (the default), each record carries the
`filename` and `lineno` of the call that logged it, taken from the slog record's
program counter. A host that bridges another logging API onto slog — a gRPC
`grpclog.LoggerV2`, a driver's logger interface — logs from inside its adapter,
so `logger.Info` there names the adapter. `LogDepth` names the adapter's caller
instead; depth 0 is the function calling `LogDepth`, depth 1 the one above it:

```go
func (a grpcAdapter) Infof(format string, args ...any) {
    telemetry.LogDepth(context.Background(), a.logger, slog.LevelInfo, 1, fmt.Sprintf(format, args...))
}
```

Standard library `log` output bridged with `slog.NewLogLogger` already names
the right frame.

#### Log output

Rendered records go to `os.Stderr`. `WithLogOutput` sends them somewhere else:

```go
// prefixWriter tags each line so a host interleaving several language
// runtimes on one stream can tell them apart.
type prefixWriter struct {
    prefix string
    w      io.Writer
}

func (p prefixWriter) Write(b []byte) (int, error) {
    if _, err := p.w.Write(append([]byte(p.prefix), b...)); err != nil {
        return 0, err
    }
    return len(b), nil
}

// IsTerminal keeps pretty-format colors alive through the wrapper.
func (p prefixWriter) IsTerminal() bool { return true }

func main() {
    sink := prefixWriter{prefix: "🐹 ", w: os.Stderr}
    if _, err := telemetry.SetupTelemetry(telemetry.WithLogOutput(sink)); err != nil {
        log.Fatal(err)
    }
    defer telemetry.ShutdownTelemetry(context.Background())

    telemetry.GetLogger(context.Background(), "launcher").Info("startup.begin.ok")
}
```

Every renderer honours it — `console`, `json` and `pretty` alike.

A writer is a handle rather than a string, so no environment variable names it
and it is not part of `TelemetryConfig`. It sits beside `WithTracerProvider`
and friends. `ReconfigureTelemetry` accepts it as well, so a host can move its
log destination without tearing the runtime down; a reconfigure that does not
pass it leaves the installed writer alone (absent means unchanged, not
cleared), and `UpdateRuntimeConfig` and `ReloadRuntimeFromEnv` never touch it.
`ShutdownTelemetry` releases it.

What the option guarantees, and what it asks of your writer:

- **Writes are serialized.** `GetLogger` builds a handler per call and each one
  owns a private mutex, so the SDK locks around the shared writer for you. Your
  writer need not be safe for concurrent use.
- **`Flush() error` is called on shutdown**, so a `bufio.Writer` does not lose
  its tail.
- **A nil writer is a `ConfigurationError`**, including a nil pointer inside a
  non-nil interface. Falling back to `os.Stderr` would put your records
  somewhere you did not ask for.
- **A panicking writer costs only the record it was writing.** The panic is
  recovered and counted as a log export failure.
- **A record your writer logs from inside its own `Write` or `Flush` is
  dropped, not deadlocked on.** Logging through this SDK there re-enters the
  serialized sink on the goroutine that holds it. That nested record never
  reaches your writer and counts as a log export failure; the record being
  written is unaffected. Writes from other goroutines still wait their turn and
  are never dropped. To see the writer's own trouble, report it somewhere else,
  such as `os.Stderr` directly.

Pretty-format colors need a terminal. An `*os.File` is probed directly; any
other writer is asked, and gets colors only if it implements
`IsTerminal() bool`. Without that method a wrapper renders uncolored, which is
the safe default when the destination might be a file someone parses.

Two recipes:

```go
telemetry.SetupTelemetry(telemetry.WithLogOutput(io.Discard))      // drop rendered records
telemetry.SetupTelemetry(telemetry.WithLogOutput(&bytes.Buffer{})) // capture them to assert on
```

`io.Discard` silences the rendered stream only. When an OTLP logs endpoint is
configured, the exporter is a separate sink and keeps shipping records — set
`PROVIDE_LOG_OTLP_ENABLED=false` to stop that too.

### Tracing

```go
err := telemetry.Trace(ctx, "db.query.ok", func(spanCtx context.Context) error {
    traceID, spanID := telemetry.GetTraceContext(spanCtx)
    _ = traceID
    return doQuery(spanCtx)
})
```

### Metrics

```go
requests := telemetry.NewCounter("http.requests", telemetry.WithUnit("1"))
requests.Add(ctx, 1, slog.String("method", "GET"))

latency := telemetry.NewHistogram("http.duration_ms", telemetry.WithUnit("ms"))
latency.Record(ctx, 42)

util := telemetry.NewGauge("cpu.utilization", telemetry.WithUnit("%"))
util.Set(ctx, 72.5)
```

Observable instruments report through a callback that runs at each collection
(every Prometheus scrape, every OTLP export interval). Like the synchronous
instruments they bind to the provider live at creation, so create them after
`SetupTelemetry`; without a provider the callback never runs.

```go
depth := telemetry.NewObservableGauge("queue.depth",
    func(ctx context.Context) []telemetry.Observation {
        return []telemetry.Observation{{Value: float64(q.Len())}}
    })
defer depth.Unregister()
```

`NewObservableCounter` and `NewObservableUpDownCounter` take the same callback.
A callback that panics contributes nothing to that collection and never fails it.

### Prometheus

Prometheus can pull from the `go/otel` module, which owns the MeterProvider.
Add `prometheus` to `OTEL_METRICS_EXPORTER` (`prometheus` alone, or
`otlp,prometheus` to push as well) and mount the handler on your own server:

```go
import provideotel "github.com/provide-io/provide-telemetry/go/otel"

mux.Handle("/metrics", provideotel.MetricsHandler())
```

`MetricsHandler()` serves GET and HEAD. Before setup, after shutdown, with
metrics disabled, when the reader is not selected, or when you injected your
own MeterProvider, it answers 503 with a one-line reason rather than an empty
200. `RenderPrometheus()` returns the same output as `(body, contentType, err)`
for servers the handler does not fit.

Or let the SDK run its own listener with
`PROVIDE_METRICS_PROMETHEUS_LISTEN=true` (or `auto`): it binds
`127.0.0.1:9464` and serves `/metrics` unless `OTEL_EXPORTER_PROMETHEUS_HOST`,
`OTEL_EXPORTER_PROMETHEUS_PORT` and `PROVIDE_METRICS_PROMETHEUS_PATH` say
otherwise, and `PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG` adds TLS or basic auth.
A listener that cannot start logs `otel.prometheus_listener_failed` and sets
the health snapshot's `SetupError`; setup itself still succeeds.

Every scrape also carries the SDK's own health as `provide_telemetry_*`
series. `PROVIDE_METRICS_HEALTH_OTLP=true` exports them over OTLP as well. See
[docs/guide/configuration.md](../docs/guide/configuration.md) for the web
config format and name translation.

### Context binding

```go
ctx = telemetry.BindContext(ctx, map[string]any{"request_id": "req-abc", "user_id": 7})
// All log calls in this context include these fields automatically.
ctx = telemetry.ClearContext(ctx)
```

### Session correlation

```go
ctx = telemetry.BindSessionContext(ctx, "sess-abc-123")
sid, ok := telemetry.GetSessionID(ctx) // "sess-abc-123", true
ctx = telemetry.ClearSessionContext(ctx)
```

### W3C trace propagation

```go
// In an HTTP handler — extract incoming traceparent/tracestate.
pc := telemetry.ExtractW3CContext(req.Header)
ctx = telemetry.BindPropagationContext(ctx, pc)
```

### PII sanitization

```go
// Append a single rule (register_pii_rule in spec).
telemetry.RegisterPIIRule(telemetry.PIIRule{
    Path: []string{"user", "ssn"},
    Mode: telemetry.PIIModeRedact,
})

// Replace all rules atomically (replace_pii_rules in spec).
telemetry.ReplacePIIRules([]telemetry.PIIRule{
    {Path: []string{"card", "number"}, Mode: telemetry.PIIModeHash},
})

payload := map[string]any{"user": map[string]any{"ssn": "123-45-6789"}}
clean := telemetry.SanitizePayload(payload, true, 0)
```

Built-in: redacts `password`, `token`, `secret`, `authorization`, `api_key`, and similar keys by default.

### Reserved root fields

The SDK stamps `service.name`, `service.env`, `service.version` and, while a
span is live, `trace.id` and `span.id` on every record. A root attribute you
pass under one of those keys, or under its cross-language name (`service`,
`env`, `version`, `trace_id`, `span_id`), is replaced by the stamped value, not
duplicated. To name a remote service, use `peer.service`.

### Cardinality guards

```go
telemetry.RegisterCardinalityLimit("http.route", telemetry.CardinalityLimit{
    MaxValues:  500,
    TTLSeconds: 3600,
})

safe := telemetry.GuardAttributes(map[string]string{
    "http.route": "/api/users/42",
})
```

### Backpressure

```go
ticket := telemetry.TryAcquire("logs")
if ticket == nil {
    return
}
defer telemetry.Release(ticket)
```

`Release` takes the `*QueueTicket` returned by `TryAcquire`, which keeps queue
ownership tied to the acquired slot.

### Health snapshot

```go
snap := telemetry.GetHealthSnapshot()
fmt.Println(snap.LogsEmitted, snap.TracesEmitted, snap.LogsCircuitOpenCount)
```

A log record counts in `LogsEmitted` once the writer and backend have run (a
write error also counts in `LogsExportFailures`). One refused before export —
by consent, sampling or backpressure — counts in `LogsDropped` instead, never
in both.

### Runtime inspection

```go
cfg := telemetry.GetRuntimeConfig()
status := telemetry.GetRuntimeStatus()

fmt.Println(cfg.ServiceName)
fmt.Println(status.SetupDone, status.Providers.Traces, status.Fallback.Logs)
```

Use `GetRuntimeConfig()` to see the applied config snapshot after setup or
runtime reloads, and `GetRuntimeStatus()` to inspect provider install state,
fallback mode, and the last setup error without digging into internals.

### Schema validation

```go
rec, err := telemetry.Event("db", "query", "ok")            // rec.Event == "db.query.ok"
name, err := telemetry.EventName("http", "request", "ok")  // "http.request.ok"
err = telemetry.ValidateEventName("db.query.ok")           // nil
```

### SLO helpers

```go
tags := telemetry.ClassifyError("TimeoutError", 0)
// map[string]string{"error.category":"timeout", "error.severity":"info", ...}

telemetry.RecordREDMetrics("/api/users", "GET", 200, 14.2)
telemetry.RecordUSEMetrics("cpu", 72)
```

### Testing helpers

```go
func TestMyThing(t *testing.T) {
    telemetry.ResetForTests()
    t.Cleanup(telemetry.ResetForTests)
    // ... test code ...
}
```

## Configuration

Every configuration value is an environment variable. The one setup-time input
that is not is the log destination, which is a writer rather than a string —
see [`WithLogOutput`](#log-output).

| Env var | Default | Description |
|---------|---------|-------------|
| `PROVIDE_TELEMETRY_SERVICE_NAME` | `provide-service` | Service identity |
| `PROVIDE_TELEMETRY_ENV` | `dev` | Deployment environment |
| `PROVIDE_TELEMETRY_VERSION` | `0.0.0` | Service version |
| `PROVIDE_LOG_LEVEL` | `INFO` | Log level: `TRACE` / `DEBUG` / `INFO` / `WARN` (or `WARNING`) / `ERROR` / `CRITICAL` |
| `PROVIDE_LOG_FORMAT` | `console` | Output format: `console` / `json` / `pretty` |
| `PROVIDE_LOG_PRETTY_KEY_COLOR` | `dim` | ANSI color name for keys in pretty format |
| `PROVIDE_LOG_PRETTY_VALUE_COLOR` | `""` | ANSI color name for values in pretty format |
| `PROVIDE_LOG_PRETTY_FIELDS` | `""` | Comma-separated field names to display in pretty format |
| `PROVIDE_TRACE_ENABLED` | `true` | Enable tracing |
| `PROVIDE_TRACE_SAMPLE_RATE` | `1.0` | Trace sample rate `[0.0, 1.0]` applied to the OTel SDK sampler (min with `PROVIDE_SAMPLING_TRACES_RATE`) |
| `PROVIDE_METRICS_ENABLED` | `true` | Enable metrics |
| `OTEL_METRICS_EXPORTER` | `otlp` | Comma-separated: `otlp`, `prometheus`, `none` (see [Prometheus](#prometheus)). Any other entry, or `none` mixed with others, is ignored with a `config.metrics_exporter.value_ignored` warning and named in `SetupError`; with nothing left it falls back to `otlp` |
| `PROVIDE_TELEMETRY_STRICT_CONFIG` | `false` | Make those ignored `OTEL_METRICS_EXPORTER` entries a `*ConfigurationError` instead |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | OTLP base endpoint (e.g. `http://localhost:4318`) |
| `OTEL_EXPORTER_OTLP_HEADERS` | — | Comma-separated `key=value` auth headers |
| `OTEL_EXPORTER_OTLP_CERTIFICATE` | — | PEM CA bundle trusted for OTLP over TLS |
| `OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE` / `_CLIENT_KEY` | — | PEM client certificate and key for mutual TLS |

Each OTLP variable also has a per-signal form
(`OTEL_EXPORTER_OTLP_{LOGS,TRACES,METRICS}_ENDPOINT` and so on) that wins over
the shared one. A configured certificate or key that cannot be read or loaded leaves that
signal's exporter unbuilt, logs `otlp.tls_file_unreadable` and sets the health
snapshot's `SetupError`; setup still succeeds and the other signals are
unaffected. The full list of variables is in
[docs/guide/configuration.md](../docs/guide/configuration.md).

## Spec conformance

This package implements every `required: true` symbol in
[`spec/telemetry-api.yaml`](../spec/telemetry-api.yaml), with names converted
to Go PascalCase per the spec's `naming_conventions.go` rule.

Run the conformance validator:

```bash
python3 ../spec/validate_conformance.py
```

## Requirements

- Go 1.26+

## License

Apache-2.0. See [LICENSE](../LICENSES/Apache-2.0.txt).
