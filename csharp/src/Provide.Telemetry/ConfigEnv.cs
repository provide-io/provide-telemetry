// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


namespace Provide.Telemetry;

public static class ConfigEnv
{
    public static TelemetryConfig ConfigFromEnv()
    {
        var cfg = TelemetryConfig.Default();
        cfg.ServiceName = Env("PROVIDE_TELEMETRY_SERVICE_NAME", cfg.ServiceName);
        // Accept both PROVIDE_TELEMETRY_ENV and PROVIDE_TELEMETRY_ENVIRONMENT
        cfg.Environment = Env("PROVIDE_TELEMETRY_ENV",
            Env("PROVIDE_TELEMETRY_ENVIRONMENT", cfg.Environment));
        cfg.Version = Env("PROVIDE_TELEMETRY_VERSION", cfg.Version);
        cfg.StrictSchema = EnvBool("PROVIDE_TELEMETRY_STRICT_SCHEMA", cfg.StrictSchema);

        cfg.EventSchema.StrictEventName = EnvBool("PROVIDE_TELEMETRY_STRICT_EVENT_NAME", cfg.EventSchema.StrictEventName);
        var req = Env("PROVIDE_TELEMETRY_REQUIRED_KEYS", "");
        if (!string.IsNullOrWhiteSpace(req))
        {
            cfg.EventSchema.RequiredKeys = req.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();
        }

        cfg.Logging.Level = Env("PROVIDE_LOG_LEVEL", cfg.Logging.Level);
        cfg.Logging.Format = Env("PROVIDE_LOG_FORMAT", cfg.Logging.Format);
        cfg.Logging.IncludeTimestamp = EnvBool("PROVIDE_LOG_INCLUDE_TIMESTAMP", cfg.Logging.IncludeTimestamp);
        cfg.Logging.IncludeCaller = EnvBool("PROVIDE_LOG_INCLUDE_CALLER", cfg.Logging.IncludeCaller);
        cfg.Logging.Sanitize = EnvBool("PROVIDE_LOG_SANITIZE", cfg.Logging.Sanitize);
        cfg.Logging.PiiMaxDepth = EnvInt("PROVIDE_LOG_PII_MAX_DEPTH", cfg.Logging.PiiMaxDepth);
        cfg.Logging.OtlpEndpoint = Env("PROVIDE_LOG_OTLP_ENDPOINT",
            Env("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
                Env("OTEL_EXPORTER_OTLP_ENDPOINT", cfg.Logging.OtlpEndpoint)));
        cfg.Logging.OtlpEnabled = EnvBool("PROVIDE_LOG_OTLP_ENABLED", cfg.Logging.OtlpEnabled);
        cfg.Logging.OtlpHeaders = ParseHeaders(Env("PROVIDE_LOG_OTLP_HEADERS",
            Env("OTEL_EXPORTER_OTLP_HEADERS", "")));

        cfg.Tracing.Enabled = EnvBool("PROVIDE_TRACE_ENABLED", cfg.Tracing.Enabled);
        cfg.Tracing.SampleRate = EnvDouble("PROVIDE_TRACE_SAMPLE_RATE", cfg.Tracing.SampleRate);
        cfg.Tracing.OtlpEndpoint = Env("PROVIDE_TRACE_OTLP_ENDPOINT",
            Env("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
                Env("OTEL_EXPORTER_OTLP_ENDPOINT", cfg.Tracing.OtlpEndpoint)));
        cfg.Tracing.OtlpHeaders = ParseHeaders(Env("PROVIDE_TRACE_OTLP_HEADERS",
            Env("OTEL_EXPORTER_OTLP_HEADERS", "")));

        cfg.Metrics.Enabled = EnvBool("PROVIDE_METRICS_ENABLED", cfg.Metrics.Enabled);
        cfg.Metrics.OtlpEndpoint = Env("PROVIDE_METRICS_OTLP_ENDPOINT",
            Env("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
                Env("OTEL_EXPORTER_OTLP_ENDPOINT", cfg.Metrics.OtlpEndpoint)));
        cfg.Metrics.OtlpHeaders = ParseHeaders(Env("PROVIDE_METRICS_OTLP_HEADERS",
            Env("OTEL_EXPORTER_OTLP_HEADERS", "")));

        cfg.Sampling.LogsRate = ValidateRate(EnvDouble("PROVIDE_SAMPLING_LOGS_RATE", cfg.Sampling.LogsRate), "PROVIDE_SAMPLING_LOGS_RATE");
        cfg.Sampling.TracesRate = ValidateRate(EnvDouble("PROVIDE_SAMPLING_TRACES_RATE", cfg.Sampling.TracesRate), "PROVIDE_SAMPLING_TRACES_RATE");
        cfg.Sampling.MetricsRate = ValidateRate(EnvDouble("PROVIDE_SAMPLING_METRICS_RATE", cfg.Sampling.MetricsRate), "PROVIDE_SAMPLING_METRICS_RATE");
        cfg.Tracing.SampleRate = ValidateRate(cfg.Tracing.SampleRate, "PROVIDE_TRACE_SAMPLE_RATE");

        cfg.Backpressure.LogsMaxSize = EnvInt("PROVIDE_BACKPRESSURE_LOGS_MAX_SIZE", cfg.Backpressure.LogsMaxSize);
        cfg.Backpressure.TracesMaxSize = EnvInt("PROVIDE_BACKPRESSURE_TRACES_MAX_SIZE", cfg.Backpressure.TracesMaxSize);
        cfg.Backpressure.MetricsMaxSize = EnvInt("PROVIDE_BACKPRESSURE_METRICS_MAX_SIZE", cfg.Backpressure.MetricsMaxSize);

        cfg.Exporter.LogsRetries = EnvInt("PROVIDE_EXPORTER_LOGS_RETRIES", cfg.Exporter.LogsRetries);
        cfg.Exporter.LogsFailOpen = EnvBool("PROVIDE_EXPORTER_LOGS_FAIL_OPEN", cfg.Exporter.LogsFailOpen);
        cfg.Exporter.TracesRetries = EnvInt("PROVIDE_EXPORTER_TRACES_RETRIES", cfg.Exporter.TracesRetries);
        cfg.Exporter.TracesFailOpen = EnvBool("PROVIDE_EXPORTER_TRACES_FAIL_OPEN", cfg.Exporter.TracesFailOpen);
        cfg.Exporter.MetricsRetries = EnvInt("PROVIDE_EXPORTER_METRICS_RETRIES", cfg.Exporter.MetricsRetries);
        cfg.Exporter.MetricsFailOpen = EnvBool("PROVIDE_EXPORTER_METRICS_FAIL_OPEN", cfg.Exporter.MetricsFailOpen);

        cfg.Slo.EnableRed = EnvBool("PROVIDE_SLO_ENABLE_RED", cfg.Slo.EnableRed);
        cfg.Slo.EnableUse = EnvBool("PROVIDE_SLO_ENABLE_USE", cfg.Slo.EnableUse);

        // Endpoint validation
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
        var builder = new UriBuilder(u) { UserName = user, Password = "****" };
        // Avoid encoding ****
        return $"{u.Scheme}://{user}:****@{u.Authority}{u.PathAndQuery}";
    }

    private static Dictionary<string, string> MaskHeaders(Dictionary<string, string> h) =>
        h.ToDictionary(kv => kv.Key, kv => MaskHeaderValue(kv.Value), StringComparer.OrdinalIgnoreCase);

    private static string MaskHeaderValue(string v) =>
        v.Length < 8 ? "****" : v[..4] + "****";

    private static Dictionary<string, string> ParseHeaders(string raw)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (string.IsNullOrWhiteSpace(raw)) return result;
        foreach (var part in raw.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var eq = part.IndexOf('=');
            if (eq <= 0) continue;
            result[part[..eq].Trim()] = part[(eq + 1)..].Trim();
        }
        return result;
    }

    private static string Env(string key, string fallback) =>
        Environment.GetEnvironmentVariable(key) is { Length: > 0 } v ? v : fallback;

    private static bool EnvBool(string key, bool fallback)
    {
        var v = Environment.GetEnvironmentVariable(key);
        if (string.IsNullOrWhiteSpace(v)) return fallback;
        if (bool.TryParse(v, out var b)) return b;
        if (v is "1" or "yes" or "YES" or "on" or "ON") return true;
        if (v is "0" or "no" or "NO" or "off" or "OFF") return false;
        throw new ConfigurationError($"invalid boolean for {key}: {v}");
    }

    private static int EnvInt(string key, int fallback)
    {
        var v = Environment.GetEnvironmentVariable(key);
        if (string.IsNullOrWhiteSpace(v)) return fallback;
        if (int.TryParse(v, out var n)) return n;
        throw new ConfigurationError($"invalid int for {key}: {v}");
    }

    private static double EnvDouble(string key, double fallback)
    {
        var v = Environment.GetEnvironmentVariable(key);
        if (string.IsNullOrWhiteSpace(v)) return fallback;
        if (double.TryParse(v, System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out var n)) return n;
        throw new ConfigurationError($"invalid float for {key}: {v}");
    }
}
