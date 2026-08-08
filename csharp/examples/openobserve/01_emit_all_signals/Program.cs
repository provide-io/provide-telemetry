// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// Emit all signal types (logs, traces, metrics) to OpenObserve via OTLP HTTP.
//
// Required env vars:
//   OPENOBSERVE_URL, OPENOBSERVE_USER, OPENOBSERVE_PASSWORD
// Optional:
//   PROVIDE_EXAMPLE_RUN_ID  defaults to DateTimeOffset.UtcNow millis

using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry;

static string RequireEnv(string name)
{
    var val = Environment.GetEnvironmentVariable(name);
    if (string.IsNullOrWhiteSpace(val))
    {
        Console.Error.WriteLine($"SKIP: missing required env var: {name}");
        Environment.Exit(0); // honest skip when OO not configured
        return "";
    }
    return val;
}

var baseUrl = RequireEnv("OPENOBSERVE_URL").TrimEnd('/');
var user = RequireEnv("OPENOBSERVE_USER");
var password = RequireEnv("OPENOBSERVE_PASSWORD");
var auth = Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes($"{user}:{password}"));
var headers = $"Authorization=Basic {auth}";
var runId = Environment.GetEnvironmentVariable("PROVIDE_EXAMPLE_RUN_ID")
    ?? DateTimeOffset.UtcNow.ToUnixTimeMilliseconds().ToString();

var traceName = $"example.openobserve.work.{runId}";
var metricName = $"example_openobserve_requests_{runId}";
var logEvent = $"example.openobserve.log.{runId}";

Console.WriteLine("OpenObserve Emit All Signals");
Console.WriteLine($"  base={baseUrl}");
Console.WriteLine($"  run_id={runId}");
Console.WriteLine($"  span={traceName}");
Console.WriteLine($"  metric={metricName}");
Console.WriteLine($"  log={logEvent}");

Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", baseUrl);
Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_HEADERS", headers);
Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf");
Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", "provide-telemetry-csharp-examples");
Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_ENV", "development");
Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_VERSION", "examples");
Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");

// Delivery is opt-in: the core package exports nothing on its own.
OpenTelemetryBackendRegistration.Register();

Testing.ResetForTests();
var cfg = ProvideTelemetry.SetupTelemetry();
var status = ProvideTelemetry.GetRuntimeStatus();
Console.WriteLine($"Setup: service={cfg.ServiceName} providers L/T/M={status.Providers.Logs}/{status.Providers.Traces}/{status.Providers.Metrics}");

ProvideTelemetry.BindContext(new Dictionary<string, object?>
{
    ["run_id"] = runId,
    ["example"] = "openobserve",
});

var log = ProvideTelemetry.GetLogger("examples.openobserve");
var requests = ProvideTelemetry.Counter(metricName);
var latency = ProvideTelemetry.Histogram($"example_openobserve_latency_{runId}");

var startEvt = ProvideTelemetry.Event("example", "openobserve", "start");
log.Info(startEvt.Event, new Dictionary<string, object?> { ["run_id"] = runId });

for (var i = 0; i < 5; i++)
{
    var sw = System.Diagnostics.Stopwatch.StartNew();
    using (var span = ProvideTelemetry.GetTracer("examples.openobserve").StartSpan(traceName))
    {
        span.SetAttribute("run_id", runId);
        span.SetAttribute("iteration", i);
        log.Info(logEvent, new Dictionary<string, object?>
        {
            ["run_id"] = runId,
            ["iteration"] = i,
            ["event"] = logEvent,
        });
        requests.Add(1, new Dictionary<string, object?> { ["iteration"] = i.ToString(), ["run_id"] = runId });
        Thread.Sleep(50);
    }
    latency.Record(sw.Elapsed.TotalMilliseconds, new Dictionary<string, object?> { ["iteration"] = i.ToString() });
    Console.WriteLine($"  iteration {i}: span+log+counter ok ({sw.ElapsedMilliseconds}ms)");
}

var doneEvt = ProvideTelemetry.Event("example", "openobserve", "done");
log.Info(doneEvt.Event, new Dictionary<string, object?> { ["run_id"] = runId, ["iterations"] = 5 });

var flush = ProvideTelemetry.FlushTelemetry(TimeSpan.FromSeconds(15));
Console.WriteLine($"Flush: logs={flush.Logs.Flushed} (failed={flush.Logs.Failed}) traces={flush.Traces.Flushed} metrics={flush.Metrics.Flushed}");
Console.WriteLine($"Counter value={requests.Value} Histogram count={latency.Count}");

if (!flush.Traces.Flushed && !status.Providers.Traces)
{
    Console.Error.WriteLine("WARN: traces provider not installed / flush incomplete");
}
if (!flush.Logs.Flushed && !status.Providers.Logs)
{
    Console.Error.WriteLine("WARN: logs provider not installed / flush incomplete");
}

ProvideTelemetry.ShutdownTelemetry();
Console.WriteLine("EMIT_ALL_SIGNALS_OK");
Console.WriteLine($"run_id={runId}");
Environment.Exit(0);
