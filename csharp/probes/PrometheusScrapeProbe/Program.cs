// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// Serve a counter and an observable gauge on the standalone listener until stdin closes.
//
// Tier 3 of the Prometheus contract: e2e/test_prometheus_scrape_e2e.py starts
// this with OTEL_METRICS_EXPORTER=prometheus and PROVIDE_METRICS_PROMETHEUS_LISTEN=true
// (plus a web config for the secured run), waits for "ready" on stdout, and
// checks what a real Prometheus scraped.

using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry;

if (Environment.GetEnvironmentVariable("PROVIDE_TRACE_ENABLED") is null)
{
    Environment.SetEnvironmentVariable("PROVIDE_TRACE_ENABLED", "false");
}

OpenTelemetryBackendRegistration.Register();
ProvideTelemetry.SetupTelemetry();
var error = ProvideTelemetry.GetHealthSnapshot().SetupError;
if (error.Length > 0)
{
    Console.Error.WriteLine($"prometheus-scrape-probe: FAIL — {error}");
    return 1;
}

ProvideTelemetry.Counter("e2e.scrape.requests").Add(3);
var temperature = ProvideTelemetry.ObservableGauge(
    "e2e.scrape.temperature", () => [new Observation(41.5)], unit: "Cel");

Console.WriteLine("ready");
Console.Out.Flush();
Console.In.ReadToEnd();

temperature.Unregister();
ProvideTelemetry.ShutdownTelemetry();
return 0;
