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
    /// Append the per-signal path unless the endpoint already names one, and
    /// refuse a URL the other SDKs would refuse.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Config parsing deliberately does not validate the endpoint — it carries
    /// whatever the environment said, exactly as Python's
    /// <c>TelemetryConfig.from_env</c> does, so a malformed value degrades at
    /// export time rather than crashing startup. This is the layer that Python
    /// guards with <c>validate_otlp_endpoint</c> and Go with
    /// <c>_validatedSignalEndpointURL</c>, so the same four rules apply here:
    /// an <c>http</c>/<c>https</c> scheme, a non-empty host, and a port that is
    /// either absent or an integer in 1..65535.
    /// </para>
    /// <para>
    /// The shape is checked against the raw text before <see cref="Uri"/> sees
    /// it. <c>Uri.TryCreate</c> already rejects three of these shapes on its
    /// own — <c>http://host:bad</c>, <c>:-1</c> and <c>:99999</c> — but accepts
    /// <c>ftp://</c>, <c>:0</c> and the empty port, so validating afterwards
    /// would leave the rules that matter unreachable and untestable.
    /// </para>
    /// <para>
    /// Userinfo is stripped before the port is read. Python scans the whole
    /// netloc for a colon and so rejects <c>https://user:pw@host/v1/logs</c>,
    /// which Go accepts; Go is right, because that colon separates credentials,
    /// not a port. Matching Go here is a deliberate choice not to copy a bug.
    /// </para>
    /// </remarks>
    internal static Uri BuildSignalUri(string endpoint, string signal)
    {
        var trimmed = endpoint.TrimEnd('/');
        var target = trimmed.Contains("/v1/", StringComparison.OrdinalIgnoreCase)
            ? trimmed
            : $"{trimmed}/v1/{signal}";
        // Checked against `trimmed`, not `target`: by this point `target` always
        // carries a "/v1/..." path, so validating it would make the
        // no-path-at-all branch unreachable — and "http://host" with no path is
        // the common case.
        ValidateShape(trimmed, endpoint);
        if (!Uri.TryCreate(target, UriKind.Absolute, out var uri))
        {
            throw new ConfigurationError($"invalid OTLP endpoint: {endpoint}");
        }
        return uri;
    }

    private static readonly char[] AuthorityTerminators = ['/', '?', '#'];

    /// <summary>
    /// Enforce the scheme, host and port rules on the raw endpoint text.
    /// </summary>
    private static void ValidateShape(string target, string endpoint)
    {
        var schemeEnd = target.IndexOf("://", StringComparison.Ordinal);
        if (schemeEnd < 0) throw Invalid(endpoint);
        var scheme = target[..schemeEnd];
        if (!scheme.Equals("http", StringComparison.OrdinalIgnoreCase)
            && !scheme.Equals("https", StringComparison.OrdinalIgnoreCase))
        {
            throw Invalid(endpoint);
        }

        var rest = target[(schemeEnd + 3)..];
        var authorityEnd = rest.IndexOfAny(AuthorityTerminators);
        var authority = authorityEnd < 0 ? rest : rest[..authorityEnd];
        var at = authority.LastIndexOf('@');
        var hostPort = at < 0 ? authority : authority[(at + 1)..];

        // Only a colon after the closing bracket can be a port separator; the
        // ones inside "[::1]" are the address itself.
        var afterBracket = hostPort[(hostPort.LastIndexOf(']') + 1)..];
        var colon = afterBracket.LastIndexOf(':');
        var hostLength = colon < 0 ? hostPort.Length : hostPort.Length - (afterBracket.Length - colon);
        if (hostLength == 0) throw Invalid(endpoint);
        if (colon < 0) return;

        var port = afterBracket[(colon + 1)..];
        if (!int.TryParse(port, out var parsed) || parsed < 1 || parsed > 65535)
        {
            throw Invalid(endpoint);
        }
    }

    private static ConfigurationError Invalid(string endpoint) =>
        new($"invalid OTLP endpoint: {endpoint}");

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
