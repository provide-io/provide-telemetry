// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Diagnostics.Metrics;

using OpenTelemetry;
using OpenTelemetry.Metrics;
using Provide.Telemetry.OpenTelemetry.Prometheus;
using Xunit;
using YamlDotNet.Serialization;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>
/// Name translation against every case otlptranslator v1.0.0 generated, read
/// from spec/prometheus_fixtures.yaml.
/// </summary>
[Collection("OpenTelemetry")]
public sealed class PrometheusNamesTests
{
    private static readonly Lazy<Dictionary<string, string>> InstrumentTypes = new(() =>
    {
        var text = File.ReadAllText(Path.Combine(PromFixtures.RepoRoot(), "spec", "telemetry-api.yaml"));
        var spec = new DeserializerBuilder().Build().Deserialize<Dictionary<object, object?>>(text);
        var translation = ((Dictionary<object, object?>)((Dictionary<object, object?>)spec["prometheus_metrics"]!)["translation"]!);
        return ((Dictionary<object, object?>)translation["instrument_types"]!)
            .ToDictionary(kv => (string)kv.Key, kv => (string)kv.Value!);
    });

    private static readonly string[] Strategies =
        ["UnderscoreEscapingWithSuffixes", "UnderscoreEscapingWithoutSuffixes", "NoUTF8EscapingWithSuffixes", "NoTranslation"];

    public static IEnumerable<object[]> MetricCases(string section) =>
        PromFixtures.Section(section).Select((c, i) => new object[]
        {
            $"{section}#{i}:{c.Str("name")}/{c.Str("unit")}/{c.Str("instrument")}", c,
        });

    public static IEnumerable<object[]> AllMetricCases() =>
        MetricCases("metric_names").Concat(MetricCases("translation_corpus")).Concat(MetricCases("translator_only_corpus"));

    public static IEnumerable<object[]> ExporterMetricCases() =>
        MetricCases("metric_names").Concat(MetricCases("translation_corpus"));

    [Theory]
    [MemberData(nameof(AllMetricCases))]
    public void MetricName_MatchesTheReference(string id, Dictionary<object, object?> c)
    {
        var kind = InstrumentTypes.Value[c.Str("instrument")!];
        var expected = c.Map("expected")!;
        foreach (var strategy in Strategies)
        {
            var want = expected[strategy] as string;
            Assert.True(want == PrometheusNames.MetricName(c.Str("name")!, c.Str("unit")!, kind, strategy),
                $"{id} {strategy}: want {want ?? "null"}");
        }
    }

    /// <summary>
    /// The same cases through a real meter provider and the pull reader, so the
    /// instrument type and unit the SDK reports are the ones translated.
    /// </summary>
    [Theory]
    [MemberData(nameof(ExporterMetricCases))]
    public void MetricName_ThroughTheExporter(string id, Dictionary<object, object?> c)
    {
        var meterName = "names.test." + Guid.NewGuid().ToString("N");
        using var meter = new Meter(meterName);
        var reader = new PrometheusPullReader();
        using var provider = Sdk.CreateMeterProviderBuilder().AddMeter(meterName).AddReader(reader).Build();
        Record(meter, c.Str("instrument")!, c.Str("name")!, c.Str("unit")!);
        var batch = reader.Snapshot();
        var expected = c.Map("expected")!;
        foreach (var strategy in Strategies)
        {
            var options = new RenderOptions(strategy, TargetInfo: false, Utf8: !PrometheusNames.Escapes(strategy));
            var names = PrometheusRender.FamiliesFrom(batch, options).Select(f => f.Name).ToList();
            var want = expected[strategy] as string;
            Assert.True(want is null ? names.Count == 0 : names.SequenceEqual([want]),
                $"{id} {strategy}: want {want ?? "nothing"}, got [{string.Join(",", names)}]");
        }
    }

    private static void Record(Meter meter, string instrument, string name, string unit)
    {
        switch (instrument)
        {
            case "counter": meter.CreateCounter<double>(name, unit).Add(1); break;
            case "gauge": meter.CreateGauge<double>(name, unit).Record(1); break;
            case "histogram": meter.CreateHistogram<double>(name, unit).Record(1); break;
            case "observable_counter": meter.CreateObservableCounter(name, () => 1.0, unit); break;
            case "observable_gauge": meter.CreateObservableGauge(name, () => 1.0, unit); break;
            default: meter.CreateObservableUpDownCounter(name, () => 1.0, unit); break;
        }
    }

    public static IEnumerable<object[]> LabelCases() =>
        PromFixtures.Section("label_names").Concat(PromFixtures.Section("label_corpus"))
            .Select(c => new object[] { c.Str("attribute")!, c });

    [Theory]
    [MemberData(nameof(LabelCases))]
    public void LabelName_MatchesTheReference(string attribute, Dictionary<object, object?> c)
    {
        Assert.Equal(c.Str("escaped"), PrometheusNames.LabelName(attribute, "UnderscoreEscapingWithSuffixes"));
        Assert.Equal(c.Str("escaped"), PrometheusNames.LabelName(attribute, "UnderscoreEscapingWithoutSuffixes"));
        Assert.Equal(c.Str("utf8"), PrometheusNames.LabelName(attribute, "NoUTF8EscapingWithSuffixes"));
        Assert.Equal(c.Str("utf8"), PrometheusNames.LabelName(attribute, "NoTranslation"));
    }

    [Theory]
    [MemberData(nameof(LabelCases))]
    public void Labels_TheReferenceRejectsOrReservesAreDroppedNotTheSample(string attribute, Dictionary<object, object?> c)
    {
        var escaped = c.Str("escaped");
        var labels = PrometheusRender.TranslateLabels(
            [new(attribute, "v"), new("keep", "k")], "UnderscoreEscapingWithSuffixes");
        var kept = escaped is not null && !escaped.StartsWith("__", StringComparison.Ordinal);
        Assert.Equal(kept ? new[] { escaped!, "keep" } : ["keep"], labels.Keys.ToArray());
    }

    [Theory]
    [InlineData("ms", "x_milliseconds")]
    [InlineData(" ms ", "x_milliseconds")]
    [InlineData("{req}", "x")]
    [InlineData("By/{x}", "x_bytes")]
    [InlineData("foo.bar", "x_foo_bar")]
    [InlineData("_s", "x_s")]
    [InlineData("1/", "x")]
    [InlineData("1/s", "x_per_second")]
    [InlineData("m/mo", "x_meters_per_month")]
    [InlineData("By/w", "x_bytes_per_week")]
    [InlineData("By/m", "x_bytes_per_minute")]
    [InlineData("foo_", "x_foo_")]
    [InlineData("min/y", "x_minutes_per_year")]
    [InlineData("h/h", "x_hours_per_hour")]
    [InlineData("d/d", "x_days_per_day")]
    [InlineData("s/q", "x_seconds_per_q")]
    [InlineData("q_/s", "x_q_per_second")]
    public void Units_EdgesOfTheSuffixRules(string unit, string want) =>
        Assert.Equal(want, PrometheusNames.MetricName("x", unit, PrometheusNames.Gauge, "UnderscoreEscapingWithSuffixes"));

    [Theory]
    [InlineData("us", "microseconds")]
    [InlineData("ns", "nanoseconds")]
    [InlineData("MiBy", "mebibytes")]
    [InlineData("GiBy", "gibibytes")]
    [InlineData("TiBy", "tibibytes")]
    [InlineData("KBy", "kilobytes")]
    [InlineData("MBy", "megabytes")]
    [InlineData("GBy", "gigabytes")]
    [InlineData("TBy", "terabytes")]
    [InlineData("V", "volts")]
    [InlineData("A", "amperes")]
    [InlineData("J", "joules")]
    [InlineData("W", "watts")]
    [InlineData("g", "grams")]
    [InlineData("Hz", "hertz")]
    [InlineData("%", "percent")]
    [InlineData("d", "days")]
    [InlineData("h", "hours")]
    [InlineData("min", "minutes")]
    public void Units_EveryMappedUnit(string unit, string word) =>
        Assert.Equal("x_" + word, PrometheusNames.MetricName("x", unit, PrometheusNames.Gauge, "UnderscoreEscapingWithSuffixes"));

    [Theory]
    [InlineData("requests_seconds", "s", "requests_seconds")]
    [InlineData("q_per_second", "1/s", "q_per_second")]
    [InlineData("total", "", "total_total")]
    [InlineData("ratio", "1", "ratio_ratio")]
    [InlineData("x.y", "By/s", "x.y_bytes_per_second")]
    public void Utf8WithSuffixes_SuffixesAgainstTheReference(string name, string unit, string want)
    {
        var kind = name == "total" ? PrometheusNames.MonotonicCounter : PrometheusNames.Gauge;
        Assert.Equal(want, PrometheusNames.MetricName(name, unit, kind, "NoUTF8EscapingWithSuffixes"));
    }

    [Fact]
    public void Utf8WithSuffixes_TrimsTheSuffixAndItsDelimiter()
    {
        Assert.Equal("a.x_total", PrometheusNames.MetricName("a.x.total", "", PrometheusNames.MonotonicCounter, "NoUTF8EscapingWithSuffixes"));
        Assert.Equal("a_ratio", PrometheusNames.MetricName("a_ratio", "1", PrometheusNames.Gauge, "NoUTF8EscapingWithSuffixes"));
        Assert.Equal("a_per_second", PrometheusNames.MetricName("a.per_second", "1/s", PrometheusNames.Gauge, "NoUTF8EscapingWithSuffixes"));
    }

    [Fact]
    public void Strategies_AreClassifiedByPrefixAndSuffix()
    {
        Assert.True(PrometheusNames.Escapes("UnderscoreEscapingWithoutSuffixes"));
        Assert.False(PrometheusNames.Escapes("NoTranslation"));
        Assert.True(PrometheusNames.AddsSuffixes("NoUTF8EscapingWithSuffixes"));
        Assert.False(PrometheusNames.AddsSuffixes("UnderscoreEscapingWithoutSuffixes"));
    }

    [Fact]
    public void LabelName_PrefixesALeadingDigitOnlyWhenEscaping()
    {
        Assert.Equal("key_1", PrometheusNames.LabelName("1", "UnderscoreEscapingWithSuffixes"));
        Assert.Equal("__a_b__", PrometheusNames.LabelName("__a.b__", "UnderscoreEscapingWithSuffixes"));
        Assert.Equal("a_b", PrometheusNames.LabelName("a__b", "UnderscoreEscapingWithSuffixes"));
        Assert.Null(PrometheusNames.LabelName("", "NoTranslation"));
        Assert.Null(PrometheusNames.LabelName(".", "UnderscoreEscapingWithSuffixes"));
    }
}
