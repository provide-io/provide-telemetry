// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// Record the push_ingestion instruments and push them to Prometheus over OTLP.
//
// Tier 1 of the Prometheus contract: no Prometheus-specific code, only the
// ordinary OTLP metrics exporter pointed at a Prometheus 3 OTLP receiver. The
// instruments are listed in spec/prometheus_fixtures.yaml (push_ingestion); the
// E2E test in e2e/test_prometheus_push_e2e.py queries them back.
//
// Inputs (environment):
//   OTEL_EXPORTER_OTLP_METRICS_ENDPOINT   e.g. http://127.0.0.1:9090/api/v1/otlp/v1/metrics
//   PROVIDE_TELEMETRY_SERVICE_NAME        becomes the Prometheus job label
//   PROVIDE_PROM_PROBE_PREFIX             dotted metric-name prefix for this run
//
// The C# facade takes no unit argument, so the histogram and gauge reach
// Prometheus without unit suffixes; push_ingestion.known_divergences records it.

using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry;

var prefix = Environment.GetEnvironmentVariable("PROVIDE_PROM_PROBE_PREFIX");
var endpoint = Environment.GetEnvironmentVariable("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT");
if (string.IsNullOrWhiteSpace(prefix) || string.IsNullOrWhiteSpace(endpoint))
{
    Console.Error.WriteLine("prometheus-push-probe: endpoint or prefix unset");
    return 2;
}
if (Environment.GetEnvironmentVariable("PROVIDE_TRACE_ENABLED") is null)
{
    Environment.SetEnvironmentVariable("PROVIDE_TRACE_ENABLED", "false");
}

// Delivery is opt-in: the core package exports nothing on its own.
OpenTelemetryBackendRegistration.Register();
ProvideTelemetry.SetupTelemetry();

ProvideTelemetry.Counter($"{prefix}.requests").Add(3, new Dictionary<string, object?> { ["route"] = "/a" });
ProvideTelemetry.Histogram($"{prefix}.request.duration", unit: "ms").Record(12, new Dictionary<string, object?> { ["route"] = "/a" });
ProvideTelemetry.Gauge($"{prefix}.cpu.utilization", unit: "1").Set(1, new Dictionary<string, object?> { ["core"] = "0" });

// Shutdown drains the periodic reader, which is what puts the data on the wire.
ProvideTelemetry.ShutdownTelemetry();
Console.Error.WriteLine("prometheus-push-probe: OK");
return 0;
