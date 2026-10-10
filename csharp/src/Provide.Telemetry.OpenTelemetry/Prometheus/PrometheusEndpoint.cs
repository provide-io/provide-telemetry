// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text;

using Provide.Telemetry;

namespace Provide.Telemetry.OpenTelemetry.Prometheus;

/// <summary>
/// Whether the pull endpoint can serve, and from which reader.
/// </summary>
/// <remarks>
/// The backend records a status as it installs the metrics provider and again
/// at shutdown. Every not-ready status has its own one-line 503 reason, so a
/// scrape that fails says why rather than reading as an empty process.
/// </remarks>
internal static class PrometheusEndpoint
{
    public const string NotSetUp = "not_set_up";
    public const string Ready = "ready";
    public const string ShutDown = "shut_down";
    public const string MetricsDisabled = "metrics_disabled";
    public const string HostProvider = "host_provider";
    public const string NotSelected = "not_selected";
    public const string SetupFailed = "setup_failed";

    public static readonly IReadOnlyDictionary<string, string> Reasons = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        [NotSetUp] = "provide-telemetry: metrics are not set up yet",
        [ShutDown] = "provide-telemetry: telemetry has been shut down",
        [MetricsDisabled] = "provide-telemetry: metrics are disabled (PROVIDE_METRICS_ENABLED=false)",
        [HostProvider] = "provide-telemetry: the host application owns the MeterProvider; serve its registry instead",
        [NotSelected] = "provide-telemetry: the Prometheus reader is not enabled (add prometheus to OTEL_METRICS_EXPORTER)",
        [SetupFailed] = "provide-telemetry: the metrics provider failed to start",
    };

    private static readonly object Gate = new();
    private static string _status = NotSetUp;
    private static (PrometheusPullReader Reader, RenderOptions Options)? _serving;

    /// <summary>The current status.</summary>
    public static string Status
    {
        get { lock (Gate) { return _status; } }
    }

    /// <summary>Record a not-ready status, forgetting any reader.</summary>
    public static void SetStatus(string status)
    {
        lock (Gate)
        {
            _status = status;
            _serving = null;
        }
    }

    /// <summary>Record that <paramref name="reader"/>, attached to the installed provider, can serve.</summary>
    public static void MarkReady(PrometheusPullReader reader, RenderOptions options)
    {
        lock (Gate)
        {
            _status = Ready;
            _serving = (reader, options);
        }
    }

    /// <summary>The render options a config selects; scrape-time negotiation adds UTF-8.</summary>
    public static RenderOptions OptionsFor(TelemetryConfig config)
    {
        var p = config.Metrics.Prometheus;
        return new RenderOptions(p.Translation, p.ScopeLabels, p.TargetInfo) { Skip = PrometheusHealth.MetricNames };
    }

    internal static void ResetForTests() => SetStatus(NotSetUp);

    /// <summary>
    /// Run one collection and render it, with the health families after it.
    /// </summary>
    /// <exception cref="TelemetryError">Nothing to serve; the message is the reason.</exception>
    public static PrometheusPayload Render(string? accept)
    {
        (PrometheusPullReader Reader, RenderOptions Options) serving;
        lock (Gate)
        {
            serving = _serving ?? throw new TelemetryError(Reasons[_status]);
        }
        var utf8 = PrometheusRender.WantsUtf8(accept);
        var options = serving.Options with { Utf8 = utf8 };
        var families = PrometheusRender.FamiliesFrom(serving.Reader.Snapshot(), options);
        families.AddRange(PrometheusHealth.Families(Health.GetHealthSnapshot()));
        return new PrometheusPayload(
            Encoding.UTF8.GetBytes(PrometheusRender.Render(families)),
            utf8 ? PrometheusRender.ContentTypeUtf8 : PrometheusRender.ContentTypeText);
    }

    private const string PlainText = "text/plain; charset=utf-8";

    /// <summary>(status, headers, body) for one scrape; shared by <see cref="PrometheusMetrics.MetricsHandler"/> and the listener.</summary>
    public static PrometheusResponse ResponseFor(string method, string? accept)
    {
        if (method is not ("GET" or "HEAD"))
        {
            return new PrometheusResponse(
                405,
                [new("Allow", "GET, HEAD"), new("Content-Type", PlainText)],
                Encoding.UTF8.GetBytes("method not allowed\n"));
        }
        PrometheusPayload payload;
        try
        {
            payload = Render(accept);
        }
        catch (TelemetryError ex)
        {
            return new PrometheusResponse(
                503, [new("Content-Type", PlainText)], Encoding.UTF8.GetBytes(ex.Message + "\n"));
        }
        return new PrometheusResponse(
            200, [new("Content-Type", payload.ContentType)], method == "GET" ? payload.Body : []);
    }
}
