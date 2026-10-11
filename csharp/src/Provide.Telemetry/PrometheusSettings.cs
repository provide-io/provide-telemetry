// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

/// <summary>
/// Parsing and validation for the Prometheus metrics settings.
/// </summary>
/// <remarks>
/// See <c>prometheus_metrics.config_rules</c> in spec/telemetry-api.yaml. Invalid
/// values are a <see cref="ConfigurationError"/>, as for the other enum keys,
/// except in <c>OTEL_METRICS_EXPORTER</c>, whose unusable entries are warned
/// about and ignored.
/// Validation runs on the environment path and again at setup, so a config built
/// in code cannot carry a value the parser would refuse.
/// </remarks>
public static class PrometheusSettings
{
    public const string ExporterOtlp = "otlp";
    public const string ExporterPrometheus = "prometheus";
    public const string ExporterNone = "none";

    /// <summary>Registered for <c>OTEL_METRICS_EXPORTER</c> by the OTel spec, not implemented here.</summary>
    public static IReadOnlyList<string> UnsupportedExporters { get; } = ["console", "logging"];

    /// <summary>Joins ignored-value warnings, and them with other setup problems, in <c>setup_error</c>.</summary>
    public const string WarningSeparator = "; ";
    public const string ListenFalse = "false";
    public const string ListenTrue = "true";
    public const string ListenAuto = "auto";
    public const string DefaultHost = "127.0.0.1";
    public const int DefaultPort = 9464;
    public const int MaxPort = 65535;
    public const string DefaultPath = "/metrics";
    public const string DefaultTranslation = "UnderscoreEscapingWithSuffixes";

    /// <summary>The translation strategies, named as Prometheus 3's otlp.translation_strategy values.</summary>
    public static IReadOnlyList<string> TranslationStrategies { get; } =
    [
        "UnderscoreEscapingWithSuffixes",
        "UnderscoreEscapingWithoutSuffixes",
        "NoUTF8EscapingWithSuffixes",
        "NoTranslation",
    ];

    /// <summary>
    /// Parse <c>OTEL_METRICS_EXPORTER</c> into the exporters and the warnings about
    /// what was ignored: split on commas, trimmed and lowercased, empty entries
    /// dropped. Empty input means <c>otlp</c>; <c>none</c> alone means no exporters.
    /// </summary>
    /// <remarks>
    /// An entry this SDK cannot export to is dropped with a warning, as the OTel
    /// environment-variable spec asks of an unrecognised enum value; see
    /// <c>prometheus_metrics.metrics_exporter_warnings</c>. <paramref name="strict"/>
    /// turns any warning into a <see cref="ConfigurationError"/>.
    /// </remarks>
    internal static (List<string> Exporters, List<string> Warnings) ParseExporters(string? raw, bool strict)
    {
        var names = (raw ?? "")
            .Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
            .Select(n => n.ToLowerInvariant())
            .ToList();
        if (names.Count > 0 && names.All(n => n == ExporterNone)) return ([], []);
        var warnings = new List<string>();
        foreach (var name in names.Distinct(StringComparer.Ordinal))
        {
            if (UnsupportedExporters.Contains(name))
            {
                warnings.Add($"OTEL_METRICS_EXPORTER: {name} is not supported by provide-telemetry, ignored");
            }
            else if (name is not (ExporterOtlp or ExporterPrometheus or ExporterNone))
            {
                warnings.Add($"OTEL_METRICS_EXPORTER: unknown exporter {name}, ignored");
            }
        }
        if (names.Contains(ExporterNone))
        {
            warnings.Add("OTEL_METRICS_EXPORTER: none cannot be combined with other exporters, ignored");
        }
        var exporters = names.Where(n => n is ExporterOtlp or ExporterPrometheus).ToList();
        if (names.Count > 0 && exporters.Count == 0)
        {
            warnings.Add("OTEL_METRICS_EXPORTER: no supported exporter left, using otlp");
        }
        if (strict && warnings.Count > 0)
        {
            throw new ConfigurationError($"PROVIDE_TELEMETRY_STRICT_CONFIG: {string.Join(WarningSeparator, warnings)}");
        }
        return (exporters.Count > 0 ? exporters : [ExporterOtlp], warnings);
    }

    /// <summary>
    /// Parse <c>OTEL_EXPORTER_PROMETHEUS_PORT</c> as an integer; <see cref="Validate"/>,
    /// which every parsed config goes through, checks the 0-65535 range.
    /// </summary>
    internal static int ParsePort(string? raw)
    {
        var value = (raw ?? "").Trim();
        if (value.Length == 0) return DefaultPort;
        if (!int.TryParse(value, System.Globalization.NumberStyles.AllowLeadingSign,
                System.Globalization.CultureInfo.InvariantCulture, out var port))
        {
            throw new ConfigurationError(
                $"OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got '{value}'");
        }
        return port;
    }

    /// <summary>Reject a config whose Prometheus settings the environment parser would refuse.</summary>
    public static void Validate(MetricsConfig metrics)
    {
        ArgumentNullException.ThrowIfNull(metrics);
        foreach (var exporter in metrics.Exporters)
        {
            if (exporter is not (ExporterOtlp or ExporterPrometheus))
            {
                throw new ConfigurationError($"metrics exporters: unknown '{exporter}'");
            }
        }
        var p = metrics.Prometheus;
        if (p.Listen is not (ListenFalse or ListenTrue or ListenAuto))
        {
            throw new ConfigurationError(
                $"PROVIDE_METRICS_PROMETHEUS_LISTEN: want false, true or auto, got '{p.Listen}'");
        }
        if (p.Port < 0 || p.Port > MaxPort)
        {
            throw new ConfigurationError($"OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got {p.Port}");
        }
        if (!p.Path.StartsWith('/') || p.Path.Contains('?') || p.Path.Contains('#'))
        {
            throw new ConfigurationError(
                $"PROVIDE_METRICS_PROMETHEUS_PATH: want a path starting with / and no query or fragment, got '{p.Path}'");
        }
        if (!TranslationStrategies.Contains(p.Translation))
        {
            throw new ConfigurationError($"PROVIDE_METRICS_PROMETHEUS_TRANSLATION: unknown strategy '{p.Translation}'");
        }
    }
}
