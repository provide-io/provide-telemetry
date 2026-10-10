// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace Provide.Telemetry.OpenTelemetry.Prometheus;

/// <summary>Per-scrape rendering choices.</summary>
/// <param name="Utf8">The scraper negotiated <c>escaping=allow-utf-8</c>.</param>
internal sealed record RenderOptions(
    string Strategy, bool ScopeLabels = false, bool TargetInfo = true, bool Utf8 = false);

/// <summary>One sample: a name suffix (_bucket, _sum, _count or none), labels and a value.</summary>
internal sealed record Sample(string Suffix, Dictionary<string, string> Labels, double Value);

/// <summary>One metric family: a translated name, a Prometheus type and its samples.</summary>
internal sealed class Family(string name, string kind, string help = "")
{
    public string Name { get; } = name;
    public string Kind { get; } = kind;
    public string Help { get; } = help;
    public List<Sample> Samples { get; } = [];
}

/// <summary>
/// Render collected metrics in the Prometheus text exposition format.
/// </summary>
/// <remarks>
/// A port of Python's <c>_prom_render.py</c>. Names go through
/// <see cref="PrometheusNames"/>. A scraper that negotiates
/// <c>escaping=allow-utf-8</c> (Prometheus 3 does) gets the UTF-8 names of the
/// NoUTF8/NoTranslation strategies in the quoted text-format syntax; any other
/// scraper gets the UnderscoreEscaping output with the same suffix choice.
/// </remarks>
internal static class PrometheusRender
{
    public const string ContentTypeText = "text/plain; version=0.0.4; charset=utf-8; escaping=underscores";
    public const string ContentTypeUtf8 = "text/plain; version=1.0.0; charset=utf-8; escaping=allow-utf-8";
    public const string TargetInfo = "target_info";
    public const string TargetInfoHelp = "Target metadata";

    private static readonly Regex LegacyName = new("^[a-zA-Z_:][a-zA-Z0-9_:]*$", RegexOptions.Compiled);
    private static readonly Regex LegacyLabel = new("^[a-zA-Z_][a-zA-Z0-9_]*$", RegexOptions.Compiled);

    /// <summary>Whether an Accept header asks for the text format with UTF-8 names.</summary>
    public static bool WantsUtf8(string? accept)
    {
        foreach (var range in (accept ?? "").Split(','))
        {
            var parameters = range.Split(';').Select(p => p.Trim().ToLowerInvariant()).ToList();
            if (parameters[0] == "text/plain" && parameters.Skip(1).Contains("escaping=allow-utf-8")) return true;
        }
        return false;
    }

    /// <summary>The strategy to translate with for this scrape.</summary>
    public static string EffectiveStrategy(RenderOptions options)
    {
        if (PrometheusNames.Escapes(options.Strategy) || options.Utf8) return options.Strategy;
        return PrometheusNames.AddsSuffixes(options.Strategy)
            ? "UnderscoreEscapingWithSuffixes"
            : "UnderscoreEscapingWithoutSuffixes";
    }

    /// <summary>
    /// Translate attribute keys to label names, dropping keys that cannot be labels.
    /// </summary>
    /// <remarks>
    /// A key the reference rejects, or translates to a name starting with "__"
    /// (reserved by Prometheus), is dropped; the sample is kept.
    /// </remarks>
    public static Dictionary<string, string> TranslateLabels(
        IEnumerable<KeyValuePair<string, object?>> attributes, string strategy)
    {
        var labels = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var (key, value) in attributes)
        {
            var label = PrometheusNames.LabelName(key, strategy);
            if (label is not null && !label.StartsWith("__", StringComparison.Ordinal))
            {
                labels[label] = FormatAttribute(value);
            }
        }
        return labels;
    }

    private static string FormatAttribute(object? value) => value switch
    {
        null => "",
        bool b => b ? "true" : "false",
        IFormattable f => f.ToString(null, CultureInfo.InvariantCulture),
        _ => value.ToString() ?? "",
    };

    /// <summary>Convert a captured collection into families keyed by translated name, sorted by name.</summary>
    public static List<Family> FamiliesFrom(CapturedBatch batch, RenderOptions options)
    {
        var strategy = EffectiveStrategy(options);
        var families = new Dictionary<string, Family>(StringComparer.Ordinal);
        var resourceLabels = TranslateLabels(batch.Resource, strategy);
        if (options.TargetInfo && resourceLabels.Count > 0)
        {
            var info = new Family(TargetInfo, "gauge", TargetInfoHelp);
            info.Samples.Add(new Sample("", resourceLabels, 1));
            families[TargetInfo] = info;
        }
        foreach (var metric in batch.Metrics)
        {
            var scope = options.ScopeLabels ? ScopeLabels(metric) : [];
            AddMetric(families, metric, scope, strategy);
        }
        return [.. families.Values.OrderBy(f => f.Name, StringComparer.Ordinal)];
    }

    private static Dictionary<string, string> ScopeLabels(CapturedMetric metric)
    {
        var labels = new Dictionary<string, string>(StringComparer.Ordinal) { ["otel_scope_name"] = metric.ScopeName };
        if (!string.IsNullOrEmpty(metric.ScopeVersion)) labels["otel_scope_version"] = metric.ScopeVersion;
        return labels;
    }

    private static void AddMetric(
        Dictionary<string, Family> families, CapturedMetric metric, Dictionary<string, string> scope, string strategy)
    {
        var name = PrometheusNames.MetricName(metric.Name, metric.Unit, metric.Kind, strategy);
        if (name is null) return;
        if (!families.TryGetValue(name, out var family))
        {
            family = new Family(name, PromType(metric.Kind), metric.Description);
            families[name] = family;
        }
        // A second instrument under the same translated name but another type.
        if (family.Kind != PromType(metric.Kind)) return;
        foreach (var point in metric.Points)
        {
            var labels = TranslateLabels(point.Attributes, strategy);
            foreach (var (key, value) in scope) labels[key] = value;
            if (point.Buckets is null)
            {
                family.Samples.Add(new Sample("", labels, point.Value));
            }
            else
            {
                family.Samples.AddRange(HistogramSamples(point, labels));
            }
        }
    }

    /// <summary>The Prometheus type for a translation kind.</summary>
    public static string PromType(string kind) => kind switch
    {
        PrometheusNames.MonotonicCounter => "counter",
        PrometheusNames.Histogram => "histogram",
        _ => "gauge",
    };

    private static IEnumerable<Sample> HistogramSamples(CapturedPoint point, Dictionary<string, string> labels)
    {
        long running = 0;
        foreach (var (bound, count) in point.Buckets!)
        {
            running += count;
            yield return new Sample("_bucket", WithLe(labels, FormatValue(bound)), running);
        }
        yield return new Sample("_bucket", WithLe(labels, "+Inf"), point.Count);
        yield return new Sample("_sum", labels, point.Value);
        yield return new Sample("_count", labels, point.Count);
    }

    private static Dictionary<string, string> WithLe(Dictionary<string, string> labels, string le) =>
        new(labels, StringComparer.Ordinal) { ["le"] = le };

    /// <summary>Format a sample value: the shortest round-trip form; NaN, +Inf and -Inf spelled out.</summary>
    public static string FormatValue(double value)
    {
        if (double.IsNaN(value)) return "NaN";
        if (double.IsInfinity(value)) return value > 0 ? "+Inf" : "-Inf";
        return value.ToString("R", CultureInfo.InvariantCulture);
    }

    private static string EscapeHelp(string text) => text.Replace("\\", "\\\\").Replace("\n", "\\n");

    /// <summary>Escape a label value or a quoted name: backslash, newline and double quote.</summary>
    private static string EscapeQuoted(string text) => EscapeHelp(text).Replace("\"", "\\\"");

    private static IEnumerable<string> LabelPairs(Dictionary<string, string> labels) =>
        labels.Select(kv =>
            $"{(LegacyLabel.IsMatch(kv.Key) ? kv.Key : $"\"{EscapeQuoted(kv.Key)}\"")}=\"{EscapeQuoted(kv.Value)}\"");

    private static string SampleLine(string name, Dictionary<string, string> labels, double value)
    {
        var pairs = LabelPairs(labels).ToList();
        var formatted = FormatValue(value);
        if (LegacyName.IsMatch(name))
        {
            return pairs.Count > 0 ? $"{name}{{{string.Join(",", pairs)}}} {formatted}" : $"{name} {formatted}";
        }
        return $"{{\"{EscapeQuoted(name)}\"{string.Concat(pairs.Select(p => "," + p))}}} {formatted}";
    }

    /// <summary>Render families as text exposition, HELP and TYPE first in each.</summary>
    public static string Render(IEnumerable<Family> families)
    {
        var text = new StringBuilder();
        foreach (var family in families)
        {
            var header = LegacyName.IsMatch(family.Name) ? family.Name : $"\"{EscapeQuoted(family.Name)}\"";
            if (family.Help.Length > 0) text.Append("# HELP ").Append(header).Append(' ').Append(EscapeHelp(family.Help)).Append('\n');
            text.Append("# TYPE ").Append(header).Append(' ').Append(family.Kind).Append('\n');
            foreach (var sample in family.Samples)
            {
                text.Append(SampleLine(family.Name + sample.Suffix, sample.Labels, sample.Value)).Append('\n');
            }
        }
        return text.ToString();
    }
}
