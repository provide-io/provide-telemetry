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
    /// <summary>PEM CA bundle trusted for this signal's OTLP endpoint (OTEL_EXPORTER_OTLP[_SIGNAL]_CERTIFICATE).</summary>
    public string OtlpCertificate { get; set; } = "";
    /// <summary>PEM client certificate for mutual TLS (OTEL_EXPORTER_OTLP[_SIGNAL]_CLIENT_CERTIFICATE).</summary>
    public string OtlpClientCertificate { get; set; } = "";
    /// <summary>PEM private key for <see cref="OtlpClientCertificate"/> (OTEL_EXPORTER_OTLP[_SIGNAL]_CLIENT_KEY).</summary>
    public string OtlpClientKey { get; set; } = "";
    // No LogCodeAttributes here, for the same reason as the Pretty* properties
    // below. config_defaults in spec/telemetry-api.yaml lists
    // PROVIDE_LOG_CODE_ATTRIBUTES for python, typescript and go; nothing in this
    // SDK parses it and no emitter reads it. A settable property named after a
    // knob that does nothing is a promise the package does not keep.
    // No PrettyKeyColor/PrettyValueColor/PrettyFields here. config_defaults in
    // spec/telemetry-api.yaml lists PROVIDE_LOG_PRETTY_* for python, typescript,
    // go and rust only. This renderer does emit ANSI — PrettyRenderer's colour
    // constants are real and it uses them — but which colours is fixed, and
    // carrying the properties would make "pretty" look configurable in C#,
    // which is a worse answer than not offering the knob.
    public Dictionary<string, string> ModuleLevels { get; set; } = new(StringComparer.Ordinal);
}

public sealed class TracingConfig
{
    public bool Enabled { get; set; } = true;
    public double SampleRate { get; set; } = 1.0;
    public string OtlpEndpoint { get; set; } = "";
    public Dictionary<string, string> OtlpHeaders { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    /// <summary>PEM CA bundle trusted for this signal's OTLP endpoint (OTEL_EXPORTER_OTLP[_SIGNAL]_CERTIFICATE).</summary>
    public string OtlpCertificate { get; set; } = "";
    /// <summary>PEM client certificate for mutual TLS (OTEL_EXPORTER_OTLP[_SIGNAL]_CLIENT_CERTIFICATE).</summary>
    public string OtlpClientCertificate { get; set; } = "";
    /// <summary>PEM private key for <see cref="OtlpClientCertificate"/> (OTEL_EXPORTER_OTLP[_SIGNAL]_CLIENT_KEY).</summary>
    public string OtlpClientKey { get; set; } = "";
}

public sealed class MetricsConfig
{
    public bool Enabled { get; set; } = true;
    public string OtlpEndpoint { get; set; } = "";
    public Dictionary<string, string> OtlpHeaders { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    /// <summary>PEM CA bundle trusted for this signal's OTLP endpoint (OTEL_EXPORTER_OTLP[_SIGNAL]_CERTIFICATE).</summary>
    public string OtlpCertificate { get; set; } = "";
    /// <summary>PEM client certificate for mutual TLS (OTEL_EXPORTER_OTLP[_SIGNAL]_CLIENT_CERTIFICATE).</summary>
    public string OtlpClientCertificate { get; set; } = "";
    /// <summary>PEM private key for <see cref="OtlpClientCertificate"/> (OTEL_EXPORTER_OTLP[_SIGNAL]_CLIENT_KEY).</summary>
    public string OtlpClientKey { get; set; } = "";

    /// <summary>
    /// The metric exporters <c>OTEL_METRICS_EXPORTER</c> selected: <c>otlp</c> and/or
    /// <c>prometheus</c>; empty for <c>none</c>.
    /// </summary>
    public List<string> Exporters { get; set; } = [PrometheusSettings.ExporterOtlp];

    /// <summary>Also export the health metrics over OTLP (PROVIDE_METRICS_HEALTH_OTLP).</summary>
    public bool HealthOtlp { get; set; }

    /// <summary>Prometheus pull reader, handler and listener settings.</summary>
    public PrometheusConfig Prometheus { get; set; } = new();

    /// <summary>Whether OTLP metrics export is selected (it still needs an endpoint).</summary>
    public bool OtlpReaderEnabled() => Enabled && Exporters.Contains(PrometheusSettings.ExporterOtlp);

    /// <summary>Whether the standalone Prometheus listener should run.</summary>
    public bool PrometheusListenerEnabled() =>
        Enabled && (Prometheus.Listen == PrometheusSettings.ListenTrue
                    || (Prometheus.Listen == PrometheusSettings.ListenAuto
                        && Exporters.Contains(PrometheusSettings.ExporterPrometheus)));

    /// <summary>Whether the Prometheus pull reader is attached; asking for the listener implies it.</summary>
    public bool PrometheusReaderEnabled() =>
        Enabled && (Exporters.Contains(PrometheusSettings.ExporterPrometheus) || PrometheusListenerEnabled());
}

/// <summary>Prometheus settings; see <c>prometheus_metrics</c> in spec/telemetry-api.yaml.</summary>
public sealed class PrometheusConfig
{
    /// <summary><c>false</c>, <c>true</c>, or <c>auto</c> (listen when prometheus is an exporter).</summary>
    public string Listen { get; set; } = PrometheusSettings.ListenFalse;
    public string Host { get; set; } = PrometheusSettings.DefaultHost;
    /// <summary>Listener port; 0 asks the OS for a free one.</summary>
    public int Port { get; set; } = PrometheusSettings.DefaultPort;
    public string Path { get; set; } = PrometheusSettings.DefaultPath;
    public string Translation { get; set; } = PrometheusSettings.DefaultTranslation;
    public bool ScopeLabels { get; set; }
    public bool TargetInfo { get; set; } = true;
    /// <summary>Path to a Prometheus web config file; empty means plain HTTP, no auth.</summary>
    public string WebConfig { get; set; } = "";

    public PrometheusConfig Clone() => (PrometheusConfig)MemberwiseClone();
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

/// <summary>
/// The exporter knobs this SDK is given, per signal.
/// </summary>
/// <remarks>
/// Exactly the two <c>config_defaults</c> entries in
/// <c>spec/telemetry-api.yaml</c> whose <c>applicability</c> names csharp:
/// <c>PROVIDE_EXPORTER_*_RETRIES</c> and <c>PROVIDE_EXPORTER_*_FAIL_OPEN</c>.
/// Backoff, timeout and allow-blocking-event-loop were carried here too and
/// pushed into <see cref="ExporterPolicy"/> on every setup, which is how a 0.5s
/// backoff kept overriding the schema's zero that <see cref="ExporterPolicy"/>
/// deliberately defaults to, and how a caller could set a <c>TimeoutSeconds</c>
/// the exporters never applied. Backoff and timeout remain on the live policy,
/// where <c>SetExporterPolicy</c> reaches them; the config object no longer
/// offers knobs the contract does not give C#.
/// </remarks>
public sealed class ExporterPolicyConfig
{
    public int LogsRetries { get; set; }
    public bool LogsFailOpen { get; set; } = true;

    public int TracesRetries { get; set; }
    public bool TracesFailOpen { get; set; } = true;

    public int MetricsRetries { get; set; }
    public bool MetricsFailOpen { get; set; } = true;
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
                OtlpCertificate = Logging.OtlpCertificate,
                OtlpClientCertificate = Logging.OtlpClientCertificate,
                OtlpClientKey = Logging.OtlpClientKey,
                ModuleLevels = new Dictionary<string, string>(Logging.ModuleLevels, StringComparer.Ordinal),
            },
            Tracing = new TracingConfig
            {
                Enabled = Tracing.Enabled,
                SampleRate = Tracing.SampleRate,
                OtlpEndpoint = Tracing.OtlpEndpoint,
                OtlpHeaders = new Dictionary<string, string>(Tracing.OtlpHeaders, StringComparer.OrdinalIgnoreCase),
                OtlpCertificate = Tracing.OtlpCertificate,
                OtlpClientCertificate = Tracing.OtlpClientCertificate,
                OtlpClientKey = Tracing.OtlpClientKey,
            },
            Metrics = new MetricsConfig
            {
                Enabled = Metrics.Enabled,
                OtlpEndpoint = Metrics.OtlpEndpoint,
                OtlpHeaders = new Dictionary<string, string>(Metrics.OtlpHeaders, StringComparer.OrdinalIgnoreCase),
                OtlpCertificate = Metrics.OtlpCertificate,
                OtlpClientCertificate = Metrics.OtlpClientCertificate,
                OtlpClientKey = Metrics.OtlpClientKey,
                Exporters = new List<string>(Metrics.Exporters),
                HealthOtlp = Metrics.HealthOtlp,
                Prometheus = Metrics.Prometheus.Clone(),
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
                LogsFailOpen = Exporter.LogsFailOpen,
                TracesRetries = Exporter.TracesRetries,
                TracesFailOpen = Exporter.TracesFailOpen,
                MetricsRetries = Exporter.MetricsRetries,
                MetricsFailOpen = Exporter.MetricsFailOpen,
            },
            Slo = new SloConfig { EnableRed = Slo.EnableRed, EnableUse = Slo.EnableUse },
            Security = new SecurityConfig { EndpointValidation = Security.EndpointValidation },
        };
    }

    public static TelemetryConfig Default() => new();
}
