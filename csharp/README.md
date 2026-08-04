# Provide.Telemetry (C#)

Idiomatic C# implementation of provide-telemetry at API parity with Python, TypeScript, Go, and Rust.

## Requirements

- .NET 10 SDK
- Optional: OpenObserve credentials for live OTLP integration tests

## Build & test

```bash
dotnet build csharp/Provide.Telemetry.sln
dotnet test csharp/tests/Provide.Telemetry.Tests/Provide.Telemetry.Tests.csproj --nologo
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
