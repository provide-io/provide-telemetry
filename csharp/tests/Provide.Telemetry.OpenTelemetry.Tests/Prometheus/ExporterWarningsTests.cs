// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>
/// Setup warns about ignored <c>OTEL_METRICS_EXPORTER</c> entries and reports
/// them as the setup error, never failing setup
/// (<c>prometheus_metrics.metrics_exporter_warnings</c>).
/// </summary>
[Collection("OpenTelemetry")]
public sealed class ExporterWarningsTests : ListenerTestBase
{
    private const string Event = "config.metrics_exporter.value_ignored";
    private const string Console = "OTEL_METRICS_EXPORTER: console is not supported by provide-telemetry, ignored";
    private const string Unknown = "OTEL_METRICS_EXPORTER: unknown exporter statsd, ignored";
    private const string Fallback = "OTEL_METRICS_EXPORTER: no supported exporter left, using otlp";

    private List<object?> Ignored() =>
        Warnings.Where(w => w.Message == Event).Select(w => w.Fields["reason"]).ToList();

    private void Env(string exporters)
    {
        SetEnv("OTEL_METRICS_EXPORTER", exporters);
        SetEnv("PROVIDE_TRACE_ENABLED", "false");
        SetEnv("PROVIDE_LOG_OTLP_ENABLED", "false");
    }

    [Fact]
    public void Setup_SucceedsLogsEachOnceAndRecordsTheSetupError()
    {
        Env("console");
        var cfg = ProvideTelemetry.SetupTelemetry();
        Assert.Equal(["otlp"], cfg.Metrics.Exporters);
        Assert.Equal([Console, Fallback], Ignored());
        Assert.Equal(2, Warnings.Count);
        Assert.Equal($"{Console}; {Fallback}", ProvideTelemetry.GetHealthSnapshot().SetupError);
        Assert.Equal($"{Console}; {Fallback}", ProvideTelemetry.GetRuntimeStatus().SetupError);
        // A repeated setup is a no-op: nothing is logged twice.
        ProvideTelemetry.SetupTelemetry();
        Assert.Equal(2, Ignored().Count);
    }

    [Fact]
    public void Setup_IgnoredEntriesComeBeforeTlsProblems()
    {
        var config = PromConfig();
        config.Metrics.Exporters = ["otlp", "prometheus"];
        config.Metrics.ExporterWarnings = [Unknown];
        config.Metrics.OtlpEndpoint = "http://127.0.0.1:9";
        config.Metrics.OtlpCertificate = Path.Combine(Pki.Dir, "missing.pem");
        ProvideTelemetry.SetupTelemetry(config);
        var parts = ProvideTelemetry.GetHealthSnapshot().SetupError.Split("; ");
        Assert.Equal(2, parts.Length);
        Assert.Equal(Unknown, parts[0]);
        Assert.StartsWith("OTEL_EXPORTER_OTLP_CERTIFICATE=", parts[1]);
        Assert.Equal([Unknown], Ignored());
    }

    [Fact]
    public void Setup_ACleanValueRecordsNothing()
    {
        Env("prometheus");
        ProvideTelemetry.SetupTelemetry();
        Assert.Empty(Warnings);
        Assert.Equal("", ProvideTelemetry.GetHealthSnapshot().SetupError);
    }

    [Fact]
    public void Setup_StrictConfigFailsInsteadOfWarning()
    {
        Env("otlp,statsd");
        SetEnv("PROVIDE_TELEMETRY_STRICT_CONFIG", "true");
        var error = Assert.Throws<ConfigurationError>(() => ProvideTelemetry.SetupTelemetry());
        Assert.Equal($"PROVIDE_TELEMETRY_STRICT_CONFIG: {Unknown}", error.Message);
        Assert.Empty(Warnings);
    }

    [Fact]
    public void DefaultWarn_WritesThroughTheSdkLogger()
    {
        // The default sink must not throw before or after setup.
        Setup.DefaultWarn(Event, new Dictionary<string, object?> { ["reason"] = Unknown });
    }
}
