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

## Examples

See [`examples/README.md`](examples/README.md) for runnable demos:

```bash
dotnet run --project csharp/examples/telemetry/01_basic_telemetry
dotnet run --project csharp/examples/telemetry/02_w3c_propagation
# requires OPENOBSERVE_* :
dotnet run --project csharp/examples/openobserve/01_emit_all_signals
```
