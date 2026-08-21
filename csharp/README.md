# Provide.Telemetry (C#)

Idiomatic C# implementation of provide-telemetry at API parity with Python, TypeScript, Go, and Rust.

## Packages

| Package | Dependencies | What it gives you |
| --- | --- | --- |
| `Provide.Telemetry` | BCL only | The whole facade: logging, tracing, metrics, governance, health. Signals render locally. |
| `Provide.Telemetry.OpenTelemetry` | `Provide.Telemetry` + OpenTelemetry + `Microsoft.Extensions.*` | OTLP delivery for all three signals. |

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

Configuration is env-driven (`PROVIDE_*` / `OTEL_*`), matching the polyglot contract.

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

Earlier releases enforced the strict 3-5 count in relaxed mode, and
`ValidateEventName` applied the segment grammar on every call without consulting
the mode at all. See the changelog for the release that changed it.

## Examples

See [`examples/README.md`](examples/README.md) for runnable demos:

```bash
dotnet run --project csharp/examples/telemetry/01_basic_telemetry
dotnet run --project csharp/examples/telemetry/02_w3c_propagation
# requires OPENOBSERVE_* :
dotnet run --project csharp/examples/openobserve/01_emit_all_signals
```
