// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// 01_basic_telemetry — logging, tracing, and all three metric types.
//
// Demonstrates:
//   - SetupTelemetry / ShutdownTelemetry lifecycle
//   - GetLogger for structured logging
//   - Trace / StartSpan for automatic span creation
//   - Counter, Gauge, Histogram creation and recording
//   - BindContext / UnbindContext / ClearContext for structured fields

using Provide.Telemetry;

Console.WriteLine("Basic Telemetry Demo");

Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", "csharp-example-basic");
Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_ENV", "examples");

Testing.ResetForTests();
var cfg = ProvideTelemetry.SetupTelemetry();
Console.WriteLine($"Service: {cfg.ServiceName}  |  Env: {cfg.Environment}  |  LogLevel: {cfg.Logging.Level}");

var log = ProvideTelemetry.GetLogger("examples.basic");

Console.WriteLine("\nBinding structured context fields...");
ProvideTelemetry.BindContext(new Dictionary<string, object?>
{
    ["region"] = "us-east-1",
    ["tier"] = "premium",
});
var startEvt = ProvideTelemetry.Event("example", "basic", "start");
log.Info(startEvt.Event, new Dictionary<string, object?>
{
    ["event.domain"] = startEvt.Domain,
    ["event.action"] = startEvt.Action,
    ["event.status"] = startEvt.Status,
    ["detail"] = "context is bound",
});
Console.WriteLine("  Bound: region=us-east-1, tier=premium");

Console.WriteLine("\nRunning traced iterations with counter + histogram + gauge:");
var requests = ProvideTelemetry.Counter("example.basic.requests");
var latency = ProvideTelemetry.Histogram("example.basic.latency_ms");
var activeTasks = ProvideTelemetry.Gauge("example.basic.active_tasks");

for (var i = 0; i < 3; i++)
{
    var workEvt = ProvideTelemetry.Event("example", "basic", "work");
    ProvideTelemetry.Trace(workEvt.Event, () =>
    {
        var iterEvt = ProvideTelemetry.Event("example", "basic", "iteration");
        log.Info(iterEvt.Event, new Dictionary<string, object?>
        {
            ["iteration"] = i,
            ["event.domain"] = iterEvt.Domain,
            ["event.action"] = iterEvt.Action,
            ["event.status"] = iterEvt.Status,
        });
        requests.Add(1, new Dictionary<string, object?> { ["iteration"] = i.ToString() });
        latency.Record(i * 12.5, new Dictionary<string, object?> { ["iteration"] = i.ToString() });
        activeTasks.Set(1);
    });
    Console.WriteLine($"  Iteration {i}: counter +1 (value={requests.Value}), histogram {i * 12.5:F1}ms, gauge={activeTasks.Value}");
    Thread.Sleep(50);
}

Console.WriteLine("\nUnbinding 'region', then clearing all context...");
ProvideTelemetry.UnbindContext("region");
log.Info("example.basic.after_unbind", new Dictionary<string, object?> { ["detail"] = "region removed" });
Console.WriteLine("  Unbound: region");

ProvideTelemetry.ClearContext();
log.Info("example.basic.after_clear", new Dictionary<string, object?> { ["detail"] = "all context cleared" });
Console.WriteLine("  Cleared: all context fields");

var flush = ProvideTelemetry.FlushTelemetry();
Console.WriteLine($"\nFlush: logs.ok={flush.Logs.Flushed || flush.Logs.NotInstalled} traces.ok={flush.Traces.Flushed || flush.Traces.NotInstalled} metrics.ok={flush.Metrics.Flushed || flush.Metrics.NotInstalled}");

ProvideTelemetry.ShutdownTelemetry();
Console.WriteLine("\nDone!");
Environment.Exit(0);
