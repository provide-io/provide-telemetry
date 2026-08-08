// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text;

namespace Provide.Telemetry;

/// <summary>
/// Builds a <see cref="TelemetryConfig"/> from the environment.
/// </summary>
/// <remarks>
/// Only the names <c>config_defaults</c> in <c>spec/telemetry-api.yaml</c> lists
/// for C# are read. There are no aliases: an SDK that also honored
/// <c>PROVIDE_TELEMETRY_ENVIRONMENT</c> or <c>PROVIDE_LOG_OTLP_ENDPOINT</c> gave
/// a deployment a knob the other four ignore, so the same environment produced
/// different telemetry depending on which language the service happened to be.
/// </remarks>
public static class ConfigEnv
{
    public static TelemetryConfig ConfigFromEnv()
    {
        var cfg = TelemetryConfig.Default();
        cfg.ServiceName = Env("PROVIDE_TELEMETRY_SERVICE_NAME", cfg.ServiceName);
        cfg.Environment = Env("PROVIDE_TELEMETRY_ENV", cfg.Environment);
        cfg.Version = Env("PROVIDE_TELEMETRY_VERSION", cfg.Version);
        cfg.StrictSchema = EnvBool("PROVIDE_TELEMETRY_STRICT_SCHEMA", cfg.StrictSchema);

        cfg.EventSchema.StrictEventName =
            EnvBool("PROVIDE_TELEMETRY_STRICT_EVENT_NAME", cfg.EventSchema.StrictEventName);
        var req = Env("PROVIDE_TELEMETRY_REQUIRED_KEYS", "");
        if (!string.IsNullOrWhiteSpace(req))
        {
            cfg.EventSchema.RequiredKeys = req
                .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                .ToList();
        }

        cfg.Logging.Level = Env("PROVIDE_LOG_LEVEL", cfg.Logging.Level);
        cfg.Logging.Format = Env("PROVIDE_LOG_FORMAT", cfg.Logging.Format);
        cfg.Logging.IncludeTimestamp = EnvBool("PROVIDE_LOG_INCLUDE_TIMESTAMP", cfg.Logging.IncludeTimestamp);
        cfg.Logging.IncludeCaller = EnvBool("PROVIDE_LOG_INCLUDE_CALLER", cfg.Logging.IncludeCaller);
        cfg.Logging.Sanitize = EnvBool("PROVIDE_LOG_SANITIZE", cfg.Logging.Sanitize);
        cfg.Logging.PiiMaxDepth = ValidateNonNegative(
            EnvInt("PROVIDE_LOG_PII_MAX_DEPTH", cfg.Logging.PiiMaxDepth), "PROVIDE_LOG_PII_MAX_DEPTH");
        cfg.Logging.OtlpEnabled = EnvBool("PROVIDE_LOG_OTLP_ENABLED", cfg.Logging.OtlpEnabled);

        var sharedEndpoint = Env("OTEL_EXPORTER_OTLP_ENDPOINT", "");
        var sharedHeaders = ParseHeaders(Env("OTEL_EXPORTER_OTLP_HEADERS", ""));
        cfg.Logging.OtlpEndpoint = Env("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", sharedEndpoint);
        cfg.Logging.OtlpHeaders = CopyHeaders(sharedHeaders);

        cfg.Tracing.Enabled = EnvBool("PROVIDE_TRACE_ENABLED", cfg.Tracing.Enabled);
        cfg.Tracing.SampleRate = ValidateRate(
            EnvDouble("PROVIDE_TRACE_SAMPLE_RATE", cfg.Tracing.SampleRate), "PROVIDE_TRACE_SAMPLE_RATE");
        cfg.Tracing.OtlpEndpoint = Env("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", sharedEndpoint);
        cfg.Tracing.OtlpHeaders = CopyHeaders(sharedHeaders);

        cfg.Metrics.Enabled = EnvBool("PROVIDE_METRICS_ENABLED", cfg.Metrics.Enabled);
        cfg.Metrics.OtlpEndpoint = Env("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", sharedEndpoint);
        cfg.Metrics.OtlpHeaders = CopyHeaders(sharedHeaders);

        cfg.Sampling.LogsRate = ValidateRate(
            EnvDouble("PROVIDE_SAMPLING_LOGS_RATE", cfg.Sampling.LogsRate), "PROVIDE_SAMPLING_LOGS_RATE");
        cfg.Sampling.TracesRate = ValidateRate(
            EnvDouble("PROVIDE_SAMPLING_TRACES_RATE", cfg.Sampling.TracesRate), "PROVIDE_SAMPLING_TRACES_RATE");
        cfg.Sampling.MetricsRate = ValidateRate(
            EnvDouble("PROVIDE_SAMPLING_METRICS_RATE", cfg.Sampling.MetricsRate), "PROVIDE_SAMPLING_METRICS_RATE");

        cfg.Exporter.LogsRetries = ValidateRetries(
            EnvInt("PROVIDE_EXPORTER_LOGS_RETRIES", cfg.Exporter.LogsRetries), "PROVIDE_EXPORTER_LOGS_RETRIES");
        cfg.Exporter.LogsFailOpen = EnvBool("PROVIDE_EXPORTER_LOGS_FAIL_OPEN", cfg.Exporter.LogsFailOpen);
        cfg.Exporter.TracesRetries = ValidateRetries(
            EnvInt("PROVIDE_EXPORTER_TRACES_RETRIES", cfg.Exporter.TracesRetries), "PROVIDE_EXPORTER_TRACES_RETRIES");
        cfg.Exporter.TracesFailOpen = EnvBool("PROVIDE_EXPORTER_TRACES_FAIL_OPEN", cfg.Exporter.TracesFailOpen);
        cfg.Exporter.MetricsRetries = ValidateRetries(
            EnvInt("PROVIDE_EXPORTER_METRICS_RETRIES", cfg.Exporter.MetricsRetries),
            "PROVIDE_EXPORTER_METRICS_RETRIES");
        cfg.Exporter.MetricsFailOpen = EnvBool("PROVIDE_EXPORTER_METRICS_FAIL_OPEN", cfg.Exporter.MetricsFailOpen);

        if (cfg.Security.EndpointValidation)
        {
            ValidateEndpoint(cfg.Logging.OtlpEndpoint);
            ValidateEndpoint(cfg.Tracing.OtlpEndpoint);
            ValidateEndpoint(cfg.Metrics.OtlpEndpoint);
        }

        return cfg;
    }

    public static Dictionary<string, object?> RedactConfig(TelemetryConfig c)
    {
        ArgumentNullException.ThrowIfNull(c);
        return new Dictionary<string, object?>
        {
            ["service_name"] = c.ServiceName,
            ["environment"] = c.Environment,
            ["version"] = c.Version,
            ["logging"] = new Dictionary<string, object?>
            {
                ["otlp_endpoint"] = MaskEndpoint(c.Logging.OtlpEndpoint),
                ["otlp_headers"] = MaskHeaders(c.Logging.OtlpHeaders),
            },
            ["tracing"] = new Dictionary<string, object?>
            {
                ["otlp_endpoint"] = MaskEndpoint(c.Tracing.OtlpEndpoint),
                ["otlp_headers"] = MaskHeaders(c.Tracing.OtlpHeaders),
            },
            ["metrics"] = new Dictionary<string, object?>
            {
                ["otlp_endpoint"] = MaskEndpoint(c.Metrics.OtlpEndpoint),
                ["otlp_headers"] = MaskHeaders(c.Metrics.OtlpHeaders),
            },
        };
    }

    /// <summary>
    /// Retries above the shared attempt ceiling (100 = MaxExportAttempts - 1) are
    /// rejected, matching the other four language runtimes, so an identical
    /// PROVIDE_EXPORTER_*_RETRIES value behaves the same everywhere.
    /// </summary>
    private static int ValidateRetries(int v, string field)
    {
        if (v < 0)
        {
            throw new ConfigurationError($"{field} must not be negative, got {v}");
        }
        if (v > Resilience.MaxExportAttempts - 1)
        {
            throw new ConfigurationError($"{field} must be at most {Resilience.MaxExportAttempts - 1}, got {v}");
        }
        return v;
    }

    private static int ValidateNonNegative(int v, string field)
    {
        if (v < 0)
        {
            throw new ConfigurationError($"{field} must not be negative, got {v}");
        }
        return v;
    }

    private static double ValidateRate(double v, string field)
    {
        if (double.IsNaN(v) || double.IsInfinity(v) || v < 0.0 || v > 1.0)
        {
            throw new ConfigurationError($"{field} must be between 0 and 1, got {v}");
        }
        return v;
    }

    private static void ValidateEndpoint(string endpoint)
    {
        if (string.IsNullOrWhiteSpace(endpoint)) return;
        // Soft-validate only: clearly non-URI values are left for exporter fail-open
        // paths (graceful degradation). Hard-reject only impossible schemes that
        // would never be attempted by an HTTP OTLP client.
        if (!Uri.TryCreate(endpoint, UriKind.Absolute, out var uri))
        {
            return; // exporter init will fail-open
        }
        if (uri.Scheme is not ("http" or "https" or "grpc" or "grpcs"))
        {
            throw new ConfigurationError($"invalid OTLP endpoint: {endpoint}");
        }
    }

    private static string MaskEndpoint(string raw)
    {
        if (!Uri.TryCreate(raw, UriKind.Absolute, out var u) || u.UserInfo.Length == 0) return raw;
        var user = u.UserInfo.Split(':')[0];
        return $"{u.Scheme}://{user}:****@{u.Authority}{u.PathAndQuery}";
    }

    private static Dictionary<string, string> MaskHeaders(Dictionary<string, string> h) =>
        h.ToDictionary(kv => kv.Key, kv => MaskHeaderValue(kv.Value), StringComparer.OrdinalIgnoreCase);

    private static string MaskHeaderValue(string v) =>
        v.Length < 8 ? "****" : v[..4] + "****";

    private static Dictionary<string, string> CopyHeaders(Dictionary<string, string> source) =>
        new(source, StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// Parse the OTLP header list: comma-separated <c>name=value</c>, percent-decoded.
    /// </summary>
    /// <remarks>
    /// Decoding is done by hand rather than with <c>Uri.UnescapeDataString</c>'s
    /// form-decoding cousins because a literal <c>+</c> must survive: it is a
    /// legal character in a bearer token, and <c>WebUtility.UrlDecode</c> would
    /// turn <c>Bearer+token</c> into <c>Bearer token</c>. The
    /// <c>config_headers</c> fixture pins both halves — <c>%2B</c> decodes to
    /// <c>+</c> while <c>+</c> stays <c>+</c>.
    /// <para>
    /// Only the first <c>=</c> separates: a value may itself contain one. A pair
    /// with an empty name, or none at all, is skipped rather than guessed at.
    /// </para>
    /// </remarks>
    internal static Dictionary<string, string> ParseHeaders(string raw)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (string.IsNullOrWhiteSpace(raw)) return result;
        foreach (var part in raw.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var eq = part.IndexOf('=');
            if (eq <= 0) continue;
            var name = PercentDecode(part[..eq].Trim());
            if (name.Length == 0) continue;
            result[name] = PercentDecode(part[(eq + 1)..].Trim());
        }
        return result;
    }

    /// <summary>Decode every <c>%HH</c> sequence; leave everything else alone.</summary>
    internal static string PercentDecode(string value)
    {
        if (!value.Contains('%', StringComparison.Ordinal)) return value;
        var bytes = new List<byte>(value.Length);
        for (var i = 0; i < value.Length; i++)
        {
            if (value[i] == '%' && i + 2 < value.Length
                && Uri.IsHexDigit(value[i + 1]) && Uri.IsHexDigit(value[i + 2]))
            {
                bytes.Add(Convert.ToByte(value.Substring(i + 1, 2), 16));
                i += 2;
                continue;
            }
            // A stray '%' that is not a valid escape stays literal rather than
            // failing the whole header list; the operator sees what they typed.
            bytes.AddRange(Encoding.UTF8.GetBytes(value[i].ToString()));
        }
        return Encoding.UTF8.GetString(bytes.ToArray());
    }

    private static string Env(string key, string fallback) =>
        System.Environment.GetEnvironmentVariable(key) is { Length: > 0 } v ? v : fallback;

    private static bool EnvBool(string key, bool fallback)
    {
        var v = System.Environment.GetEnvironmentVariable(key);
        if (string.IsNullOrWhiteSpace(v)) return fallback;
        if (bool.TryParse(v, out var b)) return b;
        if (v is "1" or "yes" or "YES" or "on" or "ON") return true;
        if (v is "0" or "no" or "NO" or "off" or "OFF") return false;
        throw new ConfigurationError($"invalid boolean for {key}: {v}");
    }

    private static int EnvInt(string key, int fallback)
    {
        var v = System.Environment.GetEnvironmentVariable(key);
        if (string.IsNullOrWhiteSpace(v)) return fallback;
        if (int.TryParse(v, out var n)) return n;
        throw new ConfigurationError($"invalid int for {key}: {v}");
    }

    private static double EnvDouble(string key, double fallback)
    {
        var v = System.Environment.GetEnvironmentVariable(key);
        if (string.IsNullOrWhiteSpace(v)) return fallback;
        if (double.TryParse(v, System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out var n)) return n;
        throw new ConfigurationError($"invalid float for {key}: {v}");
    }
}
