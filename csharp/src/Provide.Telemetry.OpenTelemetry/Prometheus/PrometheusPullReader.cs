// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using OpenTelemetry;
using OpenTelemetry.Metrics;

namespace Provide.Telemetry.OpenTelemetry.Prometheus;

/// <summary>One metric point, copied out of the SDK's batch.</summary>
/// <param name="Value">The sum or gauge value; the sum for a histogram.</param>
/// <param name="Buckets">Explicit-bound buckets (bound, count) for a histogram, the +Inf bucket excluded; else null.</param>
internal sealed record CapturedPoint(
    IReadOnlyList<KeyValuePair<string, object?>> Attributes,
    double Value,
    long Count = 0,
    IReadOnlyList<(double Bound, long Count)>? Buckets = null);

/// <summary>One metric, copied out of the SDK's batch.</summary>
/// <param name="Kind">A <see cref="PrometheusNames"/> translation kind.</param>
internal sealed record CapturedMetric(
    string Name,
    string Unit,
    string Description,
    string Kind,
    string ScopeName,
    string? ScopeVersion,
    IReadOnlyList<CapturedPoint> Points);

/// <summary>One collection: the resource attributes and every supported metric.</summary>
internal sealed record CapturedBatch(
    IReadOnlyList<KeyValuePair<string, object?>> Resource, IReadOnlyList<CapturedMetric> Metrics)
{
    public static CapturedBatch Empty { get; } = new([], []);
}

/// <summary>
/// The exporter behind the pull reader: it copies each collected batch.
/// </summary>
/// <remarks>
/// A <see cref="Batch{T}"/> and its metric points are valid only during
/// <see cref="Export"/>, so everything the renderer needs is copied out there.
/// No <c>ExportModes.Pull</c> attribute: the SDK lets a pull-only reader
/// collect only inside its internal pull scope, which exists for its own
/// Prometheus exporter, so <c>Collect()</c> would silently return false.
/// </remarks>
internal sealed class CapturingExporter : BaseExporter<Metric>
{
    public CapturedBatch Latest { get; set; } = CapturedBatch.Empty;

    public override ExportResult Export(in Batch<Metric> batch)
    {

        var metrics = new List<CapturedMetric>();
        foreach (var metric in batch)
        {
            var captured = Capture(metric);
            if (captured is not null) metrics.Add(captured);
        }
        var resource = ParentProvider?.GetResource().Attributes
            .Select(kv => new KeyValuePair<string, object?>(kv.Key, kv.Value))
            .ToList() ?? [];
        Latest = new CapturedBatch(resource, metrics);
        return ExportResult.Success;
    }

    /// <summary>The translation kind for a metric type, or null for one this path does not export.</summary>
    internal static string? KindOf(MetricType type) => type switch
    {
        MetricType.LongSum or MetricType.DoubleSum => PrometheusNames.MonotonicCounter,
        MetricType.LongSumNonMonotonic or MetricType.DoubleSumNonMonotonic => PrometheusNames.NonMonotonicCounter,
        MetricType.LongGauge or MetricType.DoubleGauge => PrometheusNames.Gauge,
        MetricType.Histogram => PrometheusNames.Histogram,
        _ => null, // exponential histograms are not exported over this path
    };

    internal static CapturedMetric? Capture(Metric metric)
    {
        var kind = KindOf(metric.MetricType);
        if (kind is null) return null;
        var points = new List<CapturedPoint>();
        foreach (ref readonly var point in metric.GetMetricPoints())
        {
            points.Add(CapturePoint(metric.MetricType, point));
        }
        return new CapturedMetric(
            metric.Name, metric.Unit ?? "", metric.Description ?? "", kind, metric.MeterName, metric.MeterVersion,
            points);
    }

    private static CapturedPoint CapturePoint(MetricType type, in MetricPoint point)
    {
        var attributes = new List<KeyValuePair<string, object?>>();
        foreach (var tag in point.Tags) attributes.Add(tag);
        return type switch
        {
            MetricType.LongSum or MetricType.LongSumNonMonotonic => new(attributes, point.GetSumLong()),
            MetricType.DoubleSum or MetricType.DoubleSumNonMonotonic => new(attributes, point.GetSumDouble()),
            MetricType.LongGauge => new(attributes, point.GetGaugeLastValueLong()),
            MetricType.DoubleGauge => new(attributes, point.GetGaugeLastValueDouble()),
            _ => new(attributes, point.GetHistogramSum(), point.GetHistogramCount(), Buckets(point)),
        };
    }

    private static List<(double, long)> Buckets(in MetricPoint point)
    {
        var buckets = new List<(double, long)>();
        foreach (var bucket in point.GetHistogramBuckets())
        {
            if (!double.IsPositiveInfinity(bucket.ExplicitBound)) buckets.Add((bucket.ExplicitBound, bucket.BucketCount));
        }
        return buckets;
    }
}

/// <summary>
/// The Prometheus pull reader: collects on demand, always cumulative.
/// </summary>
/// <remarks>
/// <see cref="Snapshot"/> runs one collection — observable callbacks included —
/// and returns the copied batch. Concurrent scrapes are serialised, because a
/// reader collects into one exporter.
/// </remarks>
internal sealed class PrometheusPullReader : BaseExportingMetricReader
{
    private readonly CapturingExporter _exporter;
    private readonly object _gate = new();

    public PrometheusPullReader()
        : this(new CapturingExporter())
    {
    }

    private PrometheusPullReader(CapturingExporter exporter)
        : base(exporter)
    {
        _exporter = exporter;
        TemporalityPreference = MetricReaderTemporalityPreference.Cumulative;
    }

    public CapturedBatch Snapshot()
    {
        lock (_gate)
        {
            _exporter.Latest = CapturedBatch.Empty;
            Collect();
            return _exporter.Latest;
        }
    }
}
