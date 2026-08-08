// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

public sealed class LoggingConfig
{
    public string Level { get; set; } = "INFO";
    public string Format { get; set; } = "console";
    public bool IncludeTimestamp { get; set; } = true;
    public bool IncludeCaller { get; set; } = true;
    public bool Sanitize { get; set; } = true;
    public int PiiMaxDepth { get; set; }
    public string OtlpEndpoint { get; set; } = "";
    public bool OtlpEnabled { get; set; } = true;
    public Dictionary<string, string> OtlpHeaders { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public bool LogCodeAttributes { get; set; }
    public string PrettyKeyColor { get; set; } = "dim";
    public string PrettyValueColor { get; set; } = "";
    public List<string> PrettyFields { get; set; } = new();
    public Dictionary<string, string> ModuleLevels { get; set; } = new(StringComparer.Ordinal);
}

public sealed class TracingConfig
{
    public bool Enabled { get; set; } = true;
    public double SampleRate { get; set; } = 1.0;
    public string OtlpEndpoint { get; set; } = "";
    public Dictionary<string, string> OtlpHeaders { get; set; } = new(StringComparer.OrdinalIgnoreCase);
}

public sealed class MetricsConfig
{
    public bool Enabled { get; set; } = true;
    public string OtlpEndpoint { get; set; } = "";
    public Dictionary<string, string> OtlpHeaders { get; set; } = new(StringComparer.OrdinalIgnoreCase);
}

public sealed class SchemaConfig
{
    public bool StrictEventName { get; set; }
    public List<string> RequiredKeys { get; set; } = new();
}

public sealed class SamplingConfig
{
    public double LogsRate { get; set; } = 1.0;
    public double TracesRate { get; set; } = 1.0;
    public double MetricsRate { get; set; } = 1.0;
}

public sealed class BackpressureConfig
{
    public int LogsMaxSize { get; set; }
    public int TracesMaxSize { get; set; }
    public int MetricsMaxSize { get; set; }
}

public sealed class ExporterPolicyConfig
{
    public int LogsRetries { get; set; }
    public double LogsBackoffSeconds { get; set; } = 0.5;
    public double LogsTimeoutSeconds { get; set; } = 10.0;
    public bool LogsFailOpen { get; set; } = true;
    public bool LogsAllowBlockingInEventLoop { get; set; }

    public int TracesRetries { get; set; }
    public double TracesBackoffSeconds { get; set; } = 0.5;
    public double TracesTimeoutSeconds { get; set; } = 10.0;
    public bool TracesFailOpen { get; set; } = true;
    public bool TracesAllowBlockingInEventLoop { get; set; }

    public int MetricsRetries { get; set; }
    public double MetricsBackoffSeconds { get; set; } = 0.5;
    public double MetricsTimeoutSeconds { get; set; } = 10.0;
    public bool MetricsFailOpen { get; set; } = true;
    public bool MetricsAllowBlockingInEventLoop { get; set; }
}

public sealed class SloConfig
{
    public bool EnableRed { get; set; }
    public bool EnableUse { get; set; }
}

public sealed class SecurityConfig
{
    public bool EndpointValidation { get; set; } = true;
}

/// <summary>Top-level configuration for provide-telemetry.</summary>
public sealed class TelemetryConfig
{
    public string ServiceName { get; set; } = "provide-service";
    public string Environment { get; set; } = "dev";
    public string Version { get; set; } = "0.0.0";
    public bool StrictSchema { get; set; }
    /// <summary>
    /// Extra OTel resource attributes, at the top of the precedence ladder.
    /// </summary>
    /// <remarks>
    /// Explicit by construction: unlike the identity fields there is no framework
    /// default to be indistinguishable from, so anything here was chosen.
    /// </remarks>
    public Dictionary<string, string> ResourceAttributes { get; set; } = new(StringComparer.Ordinal);

    public LoggingConfig Logging { get; set; } = new();
    public TracingConfig Tracing { get; set; } = new();
    public MetricsConfig Metrics { get; set; } = new();
    public SchemaConfig EventSchema { get; set; } = new();
    public SamplingConfig Sampling { get; set; } = new();
    public BackpressureConfig Backpressure { get; set; } = new();
    public ExporterPolicyConfig Exporter { get; set; } = new();
    public SloConfig Slo { get; set; } = new();
    public SecurityConfig Security { get; set; } = new();

    public double EffectiveTracesSampleRate() =>
        Math.Min(Sampling.TracesRate, Tracing.SampleRate);

    public TelemetryConfig Clone()
    {
        return new TelemetryConfig
        {
            ServiceName = ServiceName,
            Environment = Environment,
            Version = Version,
            StrictSchema = StrictSchema,
            ResourceAttributes = new Dictionary<string, string>(ResourceAttributes, StringComparer.Ordinal),
            Logging = new LoggingConfig
            {
                Level = Logging.Level,
                Format = Logging.Format,
                IncludeTimestamp = Logging.IncludeTimestamp,
                IncludeCaller = Logging.IncludeCaller,
                Sanitize = Logging.Sanitize,
                PiiMaxDepth = Logging.PiiMaxDepth,
                OtlpEndpoint = Logging.OtlpEndpoint,
                OtlpEnabled = Logging.OtlpEnabled,
                OtlpHeaders = new Dictionary<string, string>(Logging.OtlpHeaders, StringComparer.OrdinalIgnoreCase),
                LogCodeAttributes = Logging.LogCodeAttributes,
                PrettyKeyColor = Logging.PrettyKeyColor,
                PrettyValueColor = Logging.PrettyValueColor,
                PrettyFields = new List<string>(Logging.PrettyFields),
                ModuleLevels = new Dictionary<string, string>(Logging.ModuleLevels, StringComparer.Ordinal),
            },
            Tracing = new TracingConfig
            {
                Enabled = Tracing.Enabled,
                SampleRate = Tracing.SampleRate,
                OtlpEndpoint = Tracing.OtlpEndpoint,
                OtlpHeaders = new Dictionary<string, string>(Tracing.OtlpHeaders, StringComparer.OrdinalIgnoreCase),
            },
            Metrics = new MetricsConfig
            {
                Enabled = Metrics.Enabled,
                OtlpEndpoint = Metrics.OtlpEndpoint,
                OtlpHeaders = new Dictionary<string, string>(Metrics.OtlpHeaders, StringComparer.OrdinalIgnoreCase),
            },
            EventSchema = new SchemaConfig
            {
                StrictEventName = EventSchema.StrictEventName,
                RequiredKeys = new List<string>(EventSchema.RequiredKeys),
            },
            Sampling = new SamplingConfig
            {
                LogsRate = Sampling.LogsRate,
                TracesRate = Sampling.TracesRate,
                MetricsRate = Sampling.MetricsRate,
            },
            Backpressure = new BackpressureConfig
            {
                LogsMaxSize = Backpressure.LogsMaxSize,
                TracesMaxSize = Backpressure.TracesMaxSize,
                MetricsMaxSize = Backpressure.MetricsMaxSize,
            },
            Exporter = new ExporterPolicyConfig
            {
                LogsRetries = Exporter.LogsRetries,
                LogsBackoffSeconds = Exporter.LogsBackoffSeconds,
                LogsTimeoutSeconds = Exporter.LogsTimeoutSeconds,
                LogsFailOpen = Exporter.LogsFailOpen,
                LogsAllowBlockingInEventLoop = Exporter.LogsAllowBlockingInEventLoop,
                TracesRetries = Exporter.TracesRetries,
                TracesBackoffSeconds = Exporter.TracesBackoffSeconds,
                TracesTimeoutSeconds = Exporter.TracesTimeoutSeconds,
                TracesFailOpen = Exporter.TracesFailOpen,
                TracesAllowBlockingInEventLoop = Exporter.TracesAllowBlockingInEventLoop,
                MetricsRetries = Exporter.MetricsRetries,
                MetricsBackoffSeconds = Exporter.MetricsBackoffSeconds,
                MetricsTimeoutSeconds = Exporter.MetricsTimeoutSeconds,
                MetricsFailOpen = Exporter.MetricsFailOpen,
                MetricsAllowBlockingInEventLoop = Exporter.MetricsAllowBlockingInEventLoop,
            },
            Slo = new SloConfig { EnableRed = Slo.EnableRed, EnableUse = Slo.EnableUse },
            Security = new SecurityConfig { EndpointValidation = Security.EndpointValidation },
        };
    }

    public static TelemetryConfig Default() => new();
}
