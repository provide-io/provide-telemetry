// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using OpenTelemetry.Exporter;

using Provide.Telemetry;

namespace Provide.Telemetry.OpenTelemetry;

/// <summary>Endpoint and header wiring for the OTLP exporters.</summary>
internal static class Endpoints
{
    /// <summary>Trim an endpoint to its canonical form, or null when unset.</summary>
    public static string? Normalize(string endpoint) =>
        string.IsNullOrWhiteSpace(endpoint) ? null : endpoint.Trim().TrimEnd('/');

    /// <summary>
    /// Configure one exporter entirely from the resolved config.
    /// </summary>
    /// <remarks>
    /// Every field is assigned unconditionally, including an empty header
    /// string. <c>OtlpExporterOptions</c> seeds itself from <c>OTEL_*</c> at
    /// construction, so leaving a field unset would let a process-wide
    /// environment value outrank the config object the caller passed to
    /// <c>SetupTelemetry</c>. Assigning replaces; this backend never writes to
    /// the process environment to get the same effect.
    /// </remarks>
    public static void Apply(
        OtlpExporterOptions options,
        string endpoint,
        string signal,
        IReadOnlyDictionary<string, string> headers)
    {
        options.Endpoint = BuildSignalUri(endpoint, signal);
        options.Protocol = OtlpExportProtocol.HttpProtobuf;
        options.Headers = FormatHeaders(headers);
    }

    /// <summary>
    /// Append the per-signal path unless the endpoint already names one.
    /// </summary>
    internal static Uri BuildSignalUri(string endpoint, string signal)
    {
        var trimmed = endpoint.TrimEnd('/');
        if (trimmed.Contains("/v1/", StringComparison.OrdinalIgnoreCase)) return new Uri(trimmed);
        if (!Uri.TryCreate($"{trimmed}/v1/{signal}", UriKind.Absolute, out var uri))
        {
            throw new ConfigurationError($"invalid OTLP endpoint: {endpoint}");
        }
        return uri;
    }

    /// <summary>
    /// Render headers as the exporter's comma-separated form.
    /// </summary>
    /// <remarks>
    /// Deduplicated case-insensitively because <c>OtlpExportClient</c> throws
    /// <see cref="ArgumentException"/> on a repeated header name, which would
    /// turn a duplicated key in the caller's config into a setup failure.
    /// </remarks>
    internal static string FormatHeaders(IReadOnlyDictionary<string, string> headers)
    {
        if (headers.Count == 0) return "";
        var deduplicated = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var (key, value) in headers) deduplicated[key] = value;
        return string.Join(",", deduplicated.Select(kv => $"{kv.Key}={kv.Value}"));
    }
}
