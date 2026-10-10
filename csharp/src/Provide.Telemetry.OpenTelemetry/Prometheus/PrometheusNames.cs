// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text.RegularExpressions;

namespace Provide.Telemetry.OpenTelemetry.Prometheus;

/// <summary>
/// Prometheus metric and label name translation.
/// </summary>
/// <remarks>
/// A port of github.com/prometheus/otlptranslator v1.0.0 (MetricNamer and
/// LabelNamer, without namespaces) by way of Python's <c>_prom_names.py</c>, the
/// reference named by <c>prometheus_metrics.translation</c>. The cases in
/// spec/prometheus_fixtures.yaml were generated from that library, so this must
/// reproduce it exactly rather than approximate it.
/// </remarks>
internal static class PrometheusNames
{
    public const string MonotonicCounter = "monotonic_counter";
    public const string NonMonotonicCounter = "non_monotonic_counter";
    public const string Gauge = "gauge";
    public const string Histogram = "histogram";

    private static readonly Dictionary<string, string> UnitMap = new(StringComparer.Ordinal)
    {
        ["d"] = "days",
        ["h"] = "hours",
        ["min"] = "minutes",
        ["s"] = "seconds",
        ["ms"] = "milliseconds",
        ["us"] = "microseconds",
        ["ns"] = "nanoseconds",
        ["By"] = "bytes",
        ["KiBy"] = "kibibytes",
        ["MiBy"] = "mebibytes",
        ["GiBy"] = "gibibytes",
        ["TiBy"] = "tibibytes",
        ["KBy"] = "kilobytes",
        ["MBy"] = "megabytes",
        ["GBy"] = "gigabytes",
        ["TBy"] = "terabytes",
        ["m"] = "meters",
        ["V"] = "volts",
        ["A"] = "amperes",
        ["J"] = "joules",
        ["W"] = "watts",
        ["g"] = "grams",
        ["Cel"] = "celsius",
        ["Hz"] = "hertz",
        ["1"] = "",
        ["%"] = "percent",
    };

    private static readonly Dictionary<string, string> PerUnitMap = new(StringComparer.Ordinal)
    {
        ["s"] = "second",
        ["m"] = "minute",
        ["h"] = "hour",
        ["d"] = "day",
        ["w"] = "week",
        ["mo"] = "month",
        ["y"] = "year",
    };

    /// <summary>Whether the strategy escapes names to the legacy character set.</summary>
    public static bool Escapes(string strategy) => strategy.StartsWith("UnderscoreEscaping", StringComparison.Ordinal);

    /// <summary>Whether the strategy appends unit, _total and _ratio suffixes.</summary>
    public static bool AddsSuffixes(string strategy) => strategy.EndsWith("WithSuffixes", StringComparison.Ordinal);

    // Runs of characters outside the legacy sets, "_" included where it is
    // outside the set, so replacing each run with one "_" also collapses
    // repeated underscores as the reference does.
    private static readonly Regex MetricSeparators = new("[^a-zA-Z0-9:]+", RegexOptions.Compiled);
    private static readonly Regex MetricSeparatorsKeepingUnderscore = new("[^a-zA-Z0-9:_]+", RegexOptions.Compiled);
    private static readonly Regex InvalidLabelRuns = new("[^a-zA-Z0-9]+", RegexOptions.Compiled);

    /// <summary>Split on separators, dropping empty fields (Go's strings.FieldsFunc).</summary>
    private static List<string> Tokens(Regex separators, string name) =>
        separators.Split(name).Where(t => t.Length > 0).ToList();

    private static string CleanUpUnit(string unit) => RemovePrefix(MetricSeparators.Replace(unit, "_"), "_");

    /// <summary>A unit as written, or "" when blank or an {annotation}.</summary>
    private static string UnitSuffix(string unit)
    {
        unit = unit.Trim();
        return unit.Contains('{') || unit.Contains('}') ? "" : unit;
    }

    /// <summary>The main and per-unit suffixes, e.g. ("bytes", "per_second") for By/s.</summary>
    private static (string Main, string Per) UnitSuffixes(string unit)
    {
        var slash = unit.IndexOf('/');
        var main = UnitSuffix(slash < 0 ? unit : unit[..slash]);
        var per = UnitSuffix(slash < 0 ? "" : unit[(slash + 1)..]);
        return (
            UnitMap.GetValueOrDefault(main, main),
            per.Length > 0 ? "per_" + PerUnitMap.GetValueOrDefault(per, per) : "");
    }

    private static List<string> AddUnitTokens(List<string> tokens, string main, string per)
    {
        if (tokens.Contains(main)) main = "";
        // The reference also drops a per suffix already among the tokens, but
        // that cannot happen: tokens never contain "_" and a per suffix always does.
        per = per == "per_" ? "" : RemoveSuffix(per, "_");
        if (per.Length > 0) main = RemoveSuffix(main, "_");
        return [.. tokens, .. new[] { main, per }.Where(t => t.Length > 0)];
    }

    private static string PrefixLeadingDigit(string name) =>
        name.Length > 0 && char.IsAsciiDigit(name[0]) ? "_" + name : name;

    /// <summary>Full escaping normalization with suffixes (otlptranslator normalizeName).</summary>
    private static string Normalize(string name, string unit, string kind)
    {
        var (main, per) = UnitSuffixes(unit);
        var tokens = AddUnitTokens(Tokens(MetricSeparators, name), CleanUpUnit(main), CleanUpUnit(per));
        if (kind == MonotonicCounter) tokens = [.. tokens.Where(t => t != "total"), "total"];
        if (unit == "1" && kind == Gauge) tokens = [.. tokens.Where(t => t != "ratio"), "ratio"];
        return PrefixLeadingDigit(string.Join("_", tokens));
    }

    /// <summary>Trim suffix plus one delimiter character, when something is left before it.</summary>
    private static string TrimSuffix(string name, string suffix)
    {
        var keep = name.Length - suffix.Length - 1;
        return name.EndsWith(suffix, StringComparison.Ordinal) && keep > 0 ? name[..keep] : name;
    }

    /// <summary>
    /// UTF-8 naming with suffixes (otlptranslator buildMetricName).
    /// </summary>
    /// <remarks>
    /// Outer suffixes are trimmed first and re-appended last, so the result
    /// reads name, main unit, per unit, then _total or _ratio.
    /// </remarks>
    private static string Utf8WithSuffixes(string name, string unit, string kind)
    {
        var outer = "";
        if (unit == "1" && kind == Gauge)
        {
            name = TrimSuffix(name, "ratio");
            outer = "_ratio";
        }
        if (kind == MonotonicCounter)
        {
            name = TrimSuffix(name, "total");
            outer = "_total";
        }
        var (main, per) = UnitSuffixes(unit);
        var perSuffix = "";
        if (per.Length > 0)
        {
            name = TrimSuffix(name, per);
            perSuffix = "_" + per;
        }
        if (main.Length > 0 && !name.EndsWith(main, StringComparison.Ordinal)) name = name + "_" + main;
        return name + perSuffix + outer;
    }

    /// <summary>
    /// Translate an OTel instrument name into a Prometheus metric name, or null
    /// when translation leaves no usable name (the reference rejects it).
    /// </summary>
    public static string? MetricName(string name, string unit, string kind, string strategy)
    {
        if (!Escapes(strategy)) return AddsSuffixes(strategy) ? Utf8WithSuffixes(name, unit, kind) : name;
        var result = AddsSuffixes(strategy)
            ? Normalize(name, unit, kind)
            : PrefixLeadingDigit(string.Join("_", Tokens(MetricSeparatorsKeepingUnderscore, name)));
        if (result.Length == 0 || (result != name && result.Trim('_').Length == 0)) return null;
        return result;
    }

    /// <summary>
    /// Translate an attribute key into a Prometheus label name, or null for an
    /// empty key, one that is only underscores, or one that escapes to nothing.
    /// </summary>
    public static string? LabelName(string attribute, string strategy)
    {
        if (attribute.Trim('_').Length == 0) return null;
        if (!Escapes(strategy)) return attribute;
        // A key that starts and ends with "__" keeps both; shorter such keys are
        // all underscores and were rejected above.
        var reserved = attribute.StartsWith("__", StringComparison.Ordinal)
                       && attribute.EndsWith("__", StringComparison.Ordinal);
        var body = reserved ? attribute[2..^2] : attribute;
        var sanitized = InvalidLabelRuns.Replace(body, "_");
        if (reserved) sanitized = "__" + sanitized + "__";
        if (char.IsAsciiDigit(sanitized[0])) sanitized = "key_" + sanitized;
        return sanitized.Trim('_').Length == 0 ? null : sanitized;
    }

    private static string RemovePrefix(string text, string prefix) =>
        text.StartsWith(prefix, StringComparison.Ordinal) ? text[prefix.Length..] : text;

    private static string RemoveSuffix(string text, string suffix) =>
        text.EndsWith(suffix, StringComparison.Ordinal) ? text[..^suffix.Length] : text;
}
