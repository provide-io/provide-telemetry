// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text;

using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry.Prometheus;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>
/// Resets the lifecycle, the pull endpoint and the listener around each test,
/// and clears PROVIDE_* / OTEL_* so the environment cannot steer a setup.
/// </summary>
public abstract class PromTestBase : IDisposable
{
    private readonly EnvScope _env = new();

    protected PromTestBase()
    {
        OpenTelemetryBackendRegistration.Register();
        Reset();
    }

    protected List<(string Message, IReadOnlyDictionary<string, object?> Fields)> Warnings { get; } = [];

    private void Reset()
    {
        Testing.ResetForTests();
        PrometheusListener.Stop();
        PrometheusEndpoint.ResetForTests();
        PrometheusListener.Warn = (message, fields) => Warnings.Add((message, fields));
    }

    public void Dispose()
    {
        Reset();
        PrometheusListener.Warn = PrometheusListener.DefaultWarn;
        _env.Dispose();
        GC.SuppressFinalize(this);
    }

    protected void SetEnv(string key, string? value) => _env.Set(key, value);

    /// <summary>A config selecting only the Prometheus reader; no OTLP endpoint, no traces.</summary>
    protected static TelemetryConfig PromConfig()
    {
        var config = TelemetryConfig.Default();
        config.ServiceName = "prom-test";
        config.Tracing.Enabled = false;
        config.Logging.OtlpEnabled = false;
        config.Metrics.Exporters = ["prometheus"];
        return config;
    }

    protected static string Scrape(string? accept = null) =>
        Encoding.UTF8.GetString(PrometheusMetrics.RenderPrometheus(accept).Body);

    protected static string? StderrOf(Action action)
    {
        var original = Console.Error;
        using var writer = new StringWriter();
        Console.SetError(writer);
        try
        {
            action();
        }
        finally
        {
            Console.SetError(original);
        }
        return writer.ToString();
    }
}
