// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

/// <summary>
/// Parsing and validation for the Prometheus metrics settings.
/// </summary>
/// <remarks>
/// See <c>prometheus_metrics.config_rules</c> in spec/telemetry-api.yaml. Invalid
/// values are a <see cref="ConfigurationError"/>, as for the other enum keys.
/// Validation runs on the environment path and again at setup, so a config built
/// in code cannot carry a value the parser would refuse.
/// </remarks>
public static class PrometheusSettings
{
    public const string ExporterOtlp = "otlp";
    public const string ExporterPrometheus = "prometheus";
    public const string ExporterNone = "none";
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
    /// Parse <c>OTEL_METRICS_EXPORTER</c>: split on commas, trimmed and lowercased,
    /// empty entries dropped. Empty input means <c>otlp</c>; <c>none</c> alone means
    /// no exporters and may not be combined with another.
    /// </summary>
    public static List<string> ParseExporters(string? raw)
    {
        var names = (raw ?? "")
            .Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
            .Select(n => n.ToLowerInvariant())
            .ToList();
        foreach (var name in names)
        {
            if (name is not (ExporterOtlp or ExporterPrometheus or ExporterNone))
            {
                throw new ConfigurationError($"OTEL_METRICS_EXPORTER: unknown exporter '{name}'");
            }
        }
        var exporters = names.Where(n => n != ExporterNone).ToList();
        if (names.Contains(ExporterNone))
        {
            if (exporters.Count > 0)
            {
                throw new ConfigurationError("OTEL_METRICS_EXPORTER: none cannot be combined with other exporters");
            }
            return exporters;
        }
        return names.Count > 0 ? exporters : [ExporterOtlp];
    }

    /// <summary>Parse <c>OTEL_EXPORTER_PROMETHEUS_PORT</c>: an integer in 0-65535, 0 meaning any free port.</summary>
    public static int ParsePort(string? raw)
    {
        var value = (raw ?? "").Trim();
        if (value.Length == 0) return DefaultPort;
        if (!int.TryParse(value, System.Globalization.NumberStyles.AllowLeadingSign,
                System.Globalization.CultureInfo.InvariantCulture, out var port))
        {
            throw new ConfigurationError(
                $"OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got '{value}'");
        }
        ValidatePort(port);
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
        ValidatePort(p.Port);
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

    private static void ValidatePort(int port)
    {
        if (port < 0 || port > MaxPort)
        {
            throw new ConfigurationError($"OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got {port}");
        }
    }
}
