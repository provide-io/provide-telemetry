<!--
SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
SPDX-License-Identifier: Apache-2.0
-->

# provide-telemetry/go

Structured logging + OpenTelemetry traces and metrics for Go — feature parity
with the [`provide-telemetry`](https://pypi.org/p/provide-telemetry) Python and
TypeScript packages.

## Install

```bash
go get github.com/provide-io/provide-telemetry/go
```

Requires Go 1.22+.

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
| `SetupTelemetry(opts...)` | Idempotent init from environment variables. Returns `*TelemetryConfig`. |
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
(`domain.action.status`) or 4 segments (`domain.action.resource.status`).
`EventName()` accepts 3–5 segments.

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

### Context binding

```go
ctx = telemetry.BindContext(ctx, map[string]any{"request_id": "req-abc", "user_id": 7})
// All log calls in this context include these fields automatically.
ctx = telemetry.ClearContext(ctx)
```

### Session correlation

```go
ctx = telemetry.BindSessionContext(ctx, "sess-abc-123")
sid := telemetry.GetSessionID(ctx)   // "sess-abc-123"
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

### Health snapshot

```go
snap := telemetry.GetHealthSnapshot()
fmt.Println(snap.LogsEmitted, snap.TracesEmitted, snap.LogsCircuitOpenCount)
```

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
name, err := telemetry.Event("db", "query", "ok")          // "db.query.ok"
name, err  = telemetry.EventName("http", "request", "ok")  // "http.request.ok"
err        = telemetry.ValidateEventName("db.query.ok")    // nil
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

All options can be set via environment variables:

| Env var | Default | Description |
|---------|---------|-------------|
| `PROVIDE_TELEMETRY_SERVICE_NAME` | `provide-service` | Service identity |
| `PROVIDE_TELEMETRY_ENV` | `dev` | Deployment environment |
| `PROVIDE_TELEMETRY_VERSION` | `0.0.0` | Service version |
| `PROVIDE_LOG_LEVEL` | `INFO` | Log level: `TRACE` / `DEBUG` / `INFO` / `WARN` / `ERROR` |
| `PROVIDE_LOG_FORMAT` | `console` | Output format: `console` / `json` / `pretty` |
| `PROVIDE_TRACE_ENABLED` | `true` | Enable tracing |
| `PROVIDE_TRACE_SAMPLE_RATE` | `1.0` | Trace sample rate `[0.0, 1.0]` |
| `PROVIDE_METRICS_ENABLED` | `true` | Enable metrics |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | OTLP base endpoint (e.g. `http://localhost:4318`) |
| `OTEL_EXPORTER_OTLP_HEADERS` | — | Comma-separated `key=value` auth headers |

## Spec conformance

This package implements every `required: true` symbol in
[`spec/telemetry-api.yaml`](../spec/telemetry-api.yaml), with names converted
to Go PascalCase per the spec's `naming_conventions.go` rule.

Run the conformance validator:

```bash
python3 ../spec/validate_conformance.py
```

## Requirements

- Go 1.22+

## License

Apache-2.0. See [LICENSE](../LICENSES/Apache-2.0.txt).
