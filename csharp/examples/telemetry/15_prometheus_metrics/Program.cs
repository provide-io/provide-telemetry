// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// 15_prometheus_metrics — serve a Prometheus scrape endpoint from the SDK.
//
// Demonstrates:
//   - Enabling the Prometheus pull reader with OTEL_METRICS_EXPORTER=prometheus
//     (use otlp,prometheus to push over OTLP as well)
//   - PrometheusMetrics.MetricsHandler(method, accept) from
//     Provide.Telemetry.OpenTelemetry: framework-neutral, so a route copies its
//     status, headers and body onto the response (ASP.NET Core:
//     app.MapMethods("/metrics", ["GET", "HEAD"], ctx => ...))
//   - Counter and Histogram with description and unit, plus ObservableGauge
//     whose callback runs on every scrape
//   - One in-process scrape, showing the Prometheus names the SDK renders:
//     dots become underscores, counters gain _total, units become suffixes
//   - The SDK's own health as provide_telemetry_* series in the same scrape
//
// Runs offline: the handler is called directly, so no port is bound. For the
// standalone listener instead, set PROVIDE_METRICS_PROMETHEUS_LISTEN=true
// (binds 127.0.0.1:9464, serves /metrics).

using System.Text;
using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry;

static List<string> MetricNames(string body) =>
    body.Split('\n')
        .Where(line => line.StartsWith("# TYPE ", StringComparison.Ordinal))
        .Select(line => line.Split(' ')[2])
        .ToList();

Console.WriteLine("Prometheus Metrics Demo");

// Enable the pull reader. Prometheus alone keeps the example offline.
Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", "prometheus-example");
Environment.SetEnvironmentVariable("OTEL_METRICS_EXPORTER", "prometheus");

// The pull reader is part of the OpenTelemetry backend; the core package stays OTel-free.
OpenTelemetryBackendRegistration.Register();

Testing.ResetForTests();
ProvideTelemetry.SetupTelemetry();
Console.WriteLine("OTEL_METRICS_EXPORTER=prometheus -> pull reader attached");

Console.WriteLine("\nRecording instruments:");
var checkout = new Dictionary<string, object?> { ["route"] = "/checkout" };
ProvideTelemetry.Counter("example.prom.requests", "Requests handled", "1").Add(3, checkout);
Console.WriteLine("  counter   example.prom.requests (unit 1)    +3");
var latency = ProvideTelemetry.Histogram("example.prom.latency", "Request latency", "ms");
foreach (var value in new[] { 12.5, 40.0, 87.5 })
{
    latency.Record(value, checkout);
}
Console.WriteLine("  histogram example.prom.latency (unit ms)    12.5, 40.0, 87.5");
var queueDepth = 7.0;
var depth = ProvideTelemetry.ObservableGauge(
    "example.prom.queue_depth",
    () => [new Observation(queueDepth, new Dictionary<string, object?> { ["queue"] = "jobs" })],
    "Jobs waiting",
    "1");
Console.WriteLine("  observable gauge example.prom.queue_depth   callback -> 7");

// What a route does: pass the method and Accept header in, copy the answer out.
Console.WriteLine("\nGET /metrics (in-process MetricsHandler call):");
var response = PrometheusMetrics.MetricsHandler("GET", "text/plain");
var contentType = response.Headers.FirstOrDefault(h => string.Equals(h.Key, "Content-Type", StringComparison.OrdinalIgnoreCase)).Value;
Console.WriteLine($"  {response.Status}  {contentType}");
var body = Encoding.UTF8.GetString(response.Body);
var names = MetricNames(body);

Console.WriteLine("\nYour metrics, as Prometheus names them (ms -> _milliseconds, 1 -> _ratio, counter -> _total):");
foreach (var name in names.Where(n => n.StartsWith("example_", StringComparison.Ordinal)))
{
    Console.WriteLine($"  {name}");
}
Console.WriteLine("\nSDK health series in the same scrape:");
foreach (var name in names.Where(n => n.StartsWith("provide_telemetry_", StringComparison.Ordinal)))
{
    Console.WriteLine($"  {name}");
}
var sample = body.Split('\n').FirstOrDefault(l => l.StartsWith("example_prom_queue_depth", StringComparison.Ordinal));
if (sample is not null)
{
    Console.WriteLine($"\nObservable gauge sample: {sample}");
}

depth.Unregister();
ProvideTelemetry.ShutdownTelemetry();
var after = PrometheusMetrics.MetricsHandler("GET");
Console.WriteLine($"\nAfter shutdown the handler answers {after.Status}: {Encoding.UTF8.GetString(after.Body).Trim()}");
Console.WriteLine("\nDone!");
Environment.Exit(0);
