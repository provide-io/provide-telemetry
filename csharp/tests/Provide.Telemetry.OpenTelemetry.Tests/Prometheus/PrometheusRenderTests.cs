// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Diagnostics.Metrics;

using OpenTelemetry;
using OpenTelemetry.Metrics;
using OpenTelemetry.Resources;
using Provide.Telemetry.OpenTelemetry.Prometheus;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>The text exposition renderer and the batch it renders from.</summary>
[Collection("OpenTelemetry")]
public sealed class PrometheusRenderTests
{
    private const string Escaped = "UnderscoreEscapingWithSuffixes";

    private static Dictionary<string, string> L(params string[] pairs)
    {
        var labels = new Dictionary<string, string>(StringComparer.Ordinal);
        for (var i = 0; i < pairs.Length; i += 2) labels[pairs[i]] = pairs[i + 1];
        return labels;
    }

    private static CapturedMetric Metric(
        string name, string kind, params CapturedPoint[] points) =>
        new(name, "", "", kind, "scope", null, points);

    private static CapturedPoint Point(double value, params (string, object?)[] attributes) =>
        new(attributes.Select(a => new KeyValuePair<string, object?>(a.Item1, a.Item2)).ToList(), value);

    [Theory]
    [InlineData(null, false)]
    [InlineData("", false)]
    [InlineData("text/plain", false)]
    [InlineData("text/plain;escaping=allow-utf-8", true)]
    [InlineData("application/openmetrics-text;escaping=allow-utf-8, TEXT/PLAIN ; Escaping=Allow-UTF-8 ;q=0.5", true)]
    [InlineData("application/openmetrics-text;escaping=allow-utf-8", false)]
    [InlineData("escaping=allow-utf-8", false)]
    public void WantsUtf8_OnlyForTheTextFormatWithTheEscapingParameter(string? accept, bool want) =>
        Assert.Equal(want, PrometheusRender.WantsUtf8(accept));

    [Theory]
    [InlineData("UnderscoreEscapingWithoutSuffixes", false, "UnderscoreEscapingWithoutSuffixes")]
    [InlineData("NoUTF8EscapingWithSuffixes", true, "NoUTF8EscapingWithSuffixes")]
    [InlineData("NoUTF8EscapingWithSuffixes", false, "UnderscoreEscapingWithSuffixes")]
    [InlineData("NoTranslation", false, "UnderscoreEscapingWithoutSuffixes")]
    [InlineData("NoTranslation", true, "NoTranslation")]
    public void EffectiveStrategy_FallsBackToEscapingForOldScrapers(string strategy, bool utf8, string want) =>
        Assert.Equal(want, PrometheusRender.EffectiveStrategy(new RenderOptions(strategy, Utf8: utf8)));

    [Theory]
    [InlineData(1.0, "1")]
    [InlineData(41.5, "41.5")]
    [InlineData(-0.25, "-0.25")]
    [InlineData(1e21, "1E+21")]
    [InlineData(double.NaN, "NaN")]
    [InlineData(double.PositiveInfinity, "+Inf")]
    [InlineData(double.NegativeInfinity, "-Inf")]
    public void FormatValue_RoundTripsAndSpellsOutSpecials(double value, string want) =>
        Assert.Equal(want, PrometheusRender.FormatValue(value));

    [Theory]
    [InlineData(PrometheusNames.MonotonicCounter, "counter")]
    [InlineData(PrometheusNames.NonMonotonicCounter, "gauge")]
    [InlineData(PrometheusNames.Gauge, "gauge")]
    [InlineData(PrometheusNames.Histogram, "histogram")]
    public void PromType_MapsEachKind(string kind, string want) => Assert.Equal(want, PrometheusRender.PromType(kind));

    [Fact]
    public void Render_WritesHelpTypeAndSamples()
    {
        var family = new Family("a_total", "counter", "Line one\nback\\slash");
        family.Samples.Add(new Sample("", L("route", "/a\"b\n\\"), 3));
        family.Samples.Add(new Sample("", [], 4));
        var bare = new Family("b", "gauge");
        Assert.Equal(
            "# HELP a_total Line one\\nback\\\\slash\n# TYPE a_total counter\n" +
            "a_total{route=\"/a\\\"b\\n\\\\\"} 3\na_total 4\n# TYPE b gauge\n",
            PrometheusRender.Render([family, bare]));
    }

    [Fact]
    public void Render_QuotesUtf8NamesAndLabels()
    {
        var family = new Family("http.requests_total", "counter", "h");
        family.Samples.Add(new Sample("", L("http.route", "/a", "ok", "1"), 3));
        family.Samples.Add(new Sample("", [], 1));
        Assert.Equal(
            "# HELP \"http.requests_total\" h\n# TYPE \"http.requests_total\" counter\n" +
            "{\"http.requests_total\",\"http.route\"=\"/a\",ok=\"1\"} 3\n{\"http.requests_total\"} 1\n",
            PrometheusRender.Render([family]));
    }

    [Fact]
    public void Render_NothingIsEmpty() => Assert.Equal("", PrometheusRender.Render([]));

    [Fact]
    public void TranslateLabels_FormatsValuesInvariantly()
    {
        var labels = PrometheusRender.TranslateLabels(
            [new("b", true), new("f", false), new("d", 1.5), new("n", null), new("s", "x"), new("o", new Uri("http://h/"))],
            Escaped);
        Assert.Equal(L("b", "true", "f", "false", "d", "1.5", "n", "", "s", "x", "o", "http://h/"), labels);
    }

    [Fact]
    public void FamiliesFrom_TargetInfoScopeLabelsAndSorting()
    {
        var batch = new CapturedBatch(
            [new("service.name", "svc"), new("__drop__", "x")],
            [
                new("z.metric", "", "help", PrometheusNames.Gauge, "scope", "1.2", [Point(2, ("a.b", "v"))]),
                new("a.metric", "", "", PrometheusNames.MonotonicCounter, "scope", "", [Point(1)]),
            ]);
        var families = PrometheusRender.FamiliesFrom(batch, new RenderOptions(Escaped, ScopeLabels: true));
        Assert.Equal(["a_metric_total", "target_info", "z_metric"], families.Select(f => f.Name));
        Assert.Equal(L("otel_scope_name", "scope"), families[0].Samples[0].Labels);
        Assert.Equal(L("a_b", "v", "otel_scope_name", "scope", "otel_scope_version", "1.2"), families[2].Samples[0].Labels);
        Assert.Equal("help", families[2].Help);
        Assert.Equal("Target metadata", families[1].Help);
        Assert.Equal(L("service_name", "svc"), families[1].Samples[0].Labels);

        var plain = PrometheusRender.FamiliesFrom(batch, new RenderOptions(Escaped, TargetInfo: false));
        Assert.Equal(["a_metric_total", "z_metric"], plain.Select(f => f.Name));
        Assert.Equal(L("a_b", "v"), plain[1].Samples[0].Labels);
    }

    [Fact]
    public void FamiliesFrom_NoResourceLabelsMeansNoTargetInfo()
    {
        var batch = new CapturedBatch([new("___", "y"), new("__r__", "z")], []);
        Assert.Empty(PrometheusRender.FamiliesFrom(batch, new RenderOptions(Escaped)));
    }

    [Fact]
    public void FamiliesFrom_MergesSameNameAndTypeAndSkipsTypeConflictsAndUntranslatableNames()
    {
        var batch = new CapturedBatch([],
        [
            Metric("a.b", PrometheusNames.Gauge, Point(1, ("k", "1"))),
            Metric("a_b", PrometheusNames.Gauge, Point(2, ("k", "2"))),
            Metric("a.b", PrometheusNames.Histogram, new CapturedPoint([], 3, 1, [(1.0, 1L)])),
            Metric("...", PrometheusNames.Gauge, Point(9)),
        ]);
        var families = PrometheusRender.FamiliesFrom(batch, new RenderOptions(Escaped));
        var family = Assert.Single(families);
        Assert.Equal("gauge", family.Kind);
        Assert.Equal([1.0, 2.0], family.Samples.Select(s => s.Value));
    }

    [Fact]
    public void FamiliesFrom_HistogramBucketsAreCumulative()
    {
        var point = new CapturedPoint([new("k", "v")], 17.5, 4, [(1.0, 1L), (2.5, 2L)]);
        var batch = new CapturedBatch([], [Metric("lat", PrometheusNames.Histogram, point)]);
        var family = Assert.Single(PrometheusRender.FamiliesFrom(batch, new RenderOptions(Escaped)));
        Assert.Equal("histogram", family.Kind);
        Assert.Equal(
            "# TYPE lat histogram\nlat_bucket{k=\"v\",le=\"1\"} 1\nlat_bucket{k=\"v\",le=\"2.5\"} 3\n" +
            "lat_bucket{k=\"v\",le=\"+Inf\"} 4\nlat_sum{k=\"v\"} 17.5\nlat_count{k=\"v\"} 4\n",
            PrometheusRender.Render([family]));
    }

    /// <summary>Every instrument type through the SDK, the resource and scope included.</summary>
    [Fact]
    public void PullReader_CapturesEveryTypeFromTheSdk()
    {
        var meterName = "render.test." + Guid.NewGuid().ToString("N");
        using var meter = new Meter(meterName, "9.9");
        var reader = new PrometheusPullReader();
        using var provider = Sdk.CreateMeterProviderBuilder()
            .SetResourceBuilder(global::OpenTelemetry.Resources.ResourceBuilder.CreateEmpty().AddAttributes([new("service.name", "svc")]))
            .AddMeter(meterName).AddReader(reader).Build();
        meter.CreateCounter<long>("c.long", "By").Add(2, new KeyValuePair<string, object?>("k", "v"));
        meter.CreateCounter<double>("c.double").Add(1.5);
        meter.CreateUpDownCounter<long>("u.long").Add(-3);
        meter.CreateUpDownCounter<double>("u.double").Add(-1.5);
        meter.CreateGauge<long>("g.long").Record(7);
        meter.CreateGauge<double>("g.double").Record(7.5);
        meter.CreateHistogram<double>("h", "s").Record(3);
        meter.CreateHistogram<double>("h.exp");

        var batch = reader.Snapshot();
        Assert.Equal([new KeyValuePair<string, object?>("service.name", "svc")], batch.Resource);
        var byName = batch.Metrics.ToDictionary(m => m.Name);
        Assert.Equal(("By", PrometheusNames.MonotonicCounter, meterName, "9.9"),
            (byName["c.long"].Unit, byName["c.long"].Kind, byName["c.long"].ScopeName, byName["c.long"].ScopeVersion));
        Assert.Equal([new KeyValuePair<string, object?>("k", "v")], byName["c.long"].Points[0].Attributes);
        Assert.Equal(2, byName["c.long"].Points[0].Value);
        Assert.Equal(1.5, byName["c.double"].Points[0].Value);
        Assert.Equal((PrometheusNames.NonMonotonicCounter, -3.0), (byName["u.long"].Kind, byName["u.long"].Points[0].Value));
        Assert.Equal(-1.5, byName["u.double"].Points[0].Value);
        Assert.Equal((PrometheusNames.Gauge, 7.0), (byName["g.long"].Kind, byName["g.long"].Points[0].Value));
        Assert.Equal(7.5, byName["g.double"].Points[0].Value);
        var h = byName["h"].Points[0];
        Assert.Equal((PrometheusNames.Histogram, 3.0, 1L), (byName["h"].Kind, h.Value, h.Count));
        Assert.DoesNotContain(h.Buckets!, b => double.IsPositiveInfinity(b.Bound));
        Assert.Equal(1, h.Buckets!.Sum(b => b.Count));
    }

    [Fact]
    public void Capture_SkipsExponentialHistograms()
    {
        Assert.Null(CapturingExporter.KindOf(MetricType.ExponentialHistogram));
        var meterName = "exp.test." + Guid.NewGuid().ToString("N");
        using var meter = new Meter(meterName);
        var reader = new PrometheusPullReader();
        using var provider = Sdk.CreateMeterProviderBuilder()
            .AddMeter(meterName)
            .AddView("h", new Base2ExponentialBucketHistogramConfiguration())
            .AddReader(reader).Build();
        meter.CreateHistogram<double>("h").Record(3);
        Assert.Empty(reader.Snapshot().Metrics);
    }

    [Fact]
    public void Exporter_WithoutAProviderHasNoResource()
    {
        using var exporter = new CapturingExporter();
        Assert.Equal(ExportResult.Success, exporter.Export(new Batch<Metric>([], 0)));
        Assert.Empty(exporter.Latest.Resource);
        Assert.Empty(exporter.Latest.Metrics);
    }
}
