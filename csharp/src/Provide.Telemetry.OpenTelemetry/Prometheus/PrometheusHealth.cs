// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;

namespace Provide.Telemetry.OpenTelemetry.Prometheus;

/// <summary>
/// The health snapshot as <c>provide_telemetry_*</c> families
/// (<c>prometheus_metrics.health_metrics</c>).
/// </summary>
/// <remarks>
/// Written straight into the pull output, not through the MeterProvider, so
/// export health stays visible when export is what is failing.
/// </remarks>
internal static class PrometheusHealth
{
    private static readonly string[] SignalNames = [Signals.Logs, Signals.Traces, Signals.Metrics];

    /// <summary>The circuit state as a number: closed 0, half-open 1, open 2, anything else -1.</summary>
    public static double CircuitValue(string state) => state switch
    {
        "closed" => 0,
        "half-open" => 1,
        "open" => 2,
        _ => -1,
    };

    public static List<Family> Families(HealthSnapshot s)
    {
        // Per signal, in the spec's order: (metric, type, value for logs/traces/metrics).
        var perSignal = new (string Metric, string Kind, double[] Values)[]
        {
            ("provide_telemetry_emitted_total", "counter", [s.LogsEmitted, s.TracesEmitted, s.MetricsEmitted]),
            ("provide_telemetry_dropped_total", "counter", [s.LogsDropped, s.TracesDropped, s.MetricsDropped]),
            ("provide_telemetry_export_failures_total", "counter",
                [s.LogsExportFailures, s.TracesExportFailures, s.MetricsExportFailures]),
            ("provide_telemetry_export_retries_total", "counter", [s.LogsRetries, s.TracesRetries, s.MetricsRetries]),
            ("provide_telemetry_export_latency_milliseconds", "gauge",
                [s.LogsExportLatencyMs, s.TracesExportLatencyMs, s.MetricsExportLatencyMs]),
            ("provide_telemetry_async_blocking_risk_total", "counter",
                [s.LogsAsyncBlockingRisk, s.TracesAsyncBlockingRisk, s.MetricsAsyncBlockingRisk]),
            ("provide_telemetry_circuit_state", "gauge",
                [CircuitValue(s.LogsCircuitState), CircuitValue(s.TracesCircuitState), CircuitValue(s.MetricsCircuitState)]),
            ("provide_telemetry_circuit_open_total", "counter",
                [s.LogsCircuitOpenCount, s.TracesCircuitOpenCount, s.MetricsCircuitOpenCount]),
        };
        var families = new List<Family>();
        foreach (var (metric, kind, values) in perSignal)
        {
            var family = new Family(metric, kind);
            for (var i = 0; i < SignalNames.Length; i++)
            {
                family.Samples.Add(new Sample(
                    "", new Dictionary<string, string>(StringComparer.Ordinal) { ["signal"] = SignalNames[i] }, values[i]));
            }
            families.Add(family);
        }
        var setupError = new Family("provide_telemetry_setup_error", "gauge");
        setupError.Samples.Add(new Sample("", [], string.IsNullOrEmpty(s.SetupError) ? 0 : 1));
        var receipts = new Family("provide_telemetry_receipt_failures_total", "counter");
        receipts.Samples.Add(new Sample("", [], s.ReceiptFailures));
        families.Add(setupError);
        families.Add(receipts);
        return families;
    }
}
