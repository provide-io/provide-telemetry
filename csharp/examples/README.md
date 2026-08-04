# Provide.Telemetry C# Examples

Thin console apps that call only the public `Provide.Telemetry` API.

## Prerequisites

- .NET 10 SDK
- Library project at `../src/Provide.Telemetry`

## Telemetry demos (no collector required)

```bash
dotnet run --project csharp/examples/telemetry/01_basic_telemetry
dotnet run --project csharp/examples/telemetry/02_w3c_propagation
```

## OpenObserve / OTLP

Requires live OpenObserve credentials (same as other language examples):

```bash
export OPENOBSERVE_URL=http://localhost:5080/api/default
export OPENOBSERVE_USER=admin@provide.test
export OPENOBSERVE_PASSWORD='…'

dotnet run --project csharp/examples/openobserve/01_emit_all_signals
```

When `OPENOBSERVE_*` is unset, the OpenObserve example exits 0 with a `SKIP:` message
(honest skip for machines without OO).

## Layout

| Path | Purpose |
|------|---------|
| `telemetry/01_basic_telemetry` | Setup, logger, spans, counter/gauge/histogram, context bind |
| `telemetry/02_w3c_propagation` | W3C extract/bind, session context |
| `openobserve/01_emit_all_signals` | OTLP HTTP traces/metrics/logs to OpenObserve |
