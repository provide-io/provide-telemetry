// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry.OpenTelemetry.Prometheus;

namespace Provide.Telemetry.OpenTelemetry;

/// <summary>One rendered collection: the exposition body and its content type.</summary>
public sealed record PrometheusPayload(byte[] Body, string ContentType);

/// <summary>A framework-neutral HTTP response for one scrape.</summary>
public sealed record PrometheusResponse(int Status, IReadOnlyList<KeyValuePair<string, string>> Headers, byte[] Body);

/// <summary>
/// The Tier 2 Prometheus pull surface (<c>prometheus_metrics</c> in spec/telemetry-api.yaml).
/// </summary>
/// <remarks>
/// Both read the pull reader setup attaches when <c>OTEL_METRICS_EXPORTER</c>
/// includes <c>prometheus</c> (or the listener is requested). Each call runs
/// one collection — observable callbacks, then the health families.
/// </remarks>
public static class PrometheusMetrics
{
    /// <summary>
    /// Render one collection in the Prometheus text format.
    /// </summary>
    /// <param name="accept">The scraper's Accept header; <c>escaping=allow-utf-8</c> allows UTF-8 names.</param>
    /// <exception cref="TelemetryError">
    /// Before setup, after shutdown, with metrics disabled, without the
    /// Prometheus reader, or when the host owns the MeterProvider; the message
    /// names which.
    /// </exception>
    public static PrometheusPayload RenderPrometheus(string? accept = null) => PrometheusEndpoint.Render(accept);

    /// <summary>
    /// Answer one scrape: 200 with the exposition for GET and HEAD, 405 for any
    /// other method, and 503 with a one-line reason when there is nothing to serve.
    /// </summary>
    /// <remarks>
    /// Framework-neutral so any server can mount it: copy the status, headers
    /// and body onto the host's response. For ASP.NET Core,
    /// <c>app.MapMethods(path, ["GET", "HEAD"], ctx => …)</c> around this call.
    /// </remarks>
    public static PrometheusResponse MetricsHandler(string method, string? accept = null)
    {
        ArgumentNullException.ThrowIfNull(method);
        return PrometheusEndpoint.ResponseFor(method, accept);
    }
}
