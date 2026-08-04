// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Diagnostics;
using System.Diagnostics.Metrics;

namespace Provide.Telemetry.Otel;

internal sealed class OtelTracer : ITracer
{
    private readonly ActivitySource _source;
    public OtelTracer(ActivitySource source, string name) { _source = source; _ = name; }
    public ISpan StartSpan(string name)
    {
        if (!Setup.IsTracingEnabled())
        {
            return DroppedSpan();
        }
        // Consent always applies. Probabilistic sampling is delegated to the SDK
        // ParentBased/TraceIdRatioBased sampler (no double-sampling) — same as Go.
        if (!Consent.ShouldAllow(Signals.Traces, ""))
        {
            return DroppedSpan();
        }
        var ticket = Backpressure.TryAcquire(Signals.Traces);
        if (ticket is null && Backpressure.GetQueuePolicy().TracesMaxSize > 0)
        {
            return DroppedSpan();
        }
        try
        {
            var activity = _source.StartActivity(name, ActivityKind.Internal);
            if (activity is null)
            {
                Backpressure.Release(ticket);
                return DroppedSpan();
            }
            Health.RecordEmitted(Signals.Traces);
            Context.SetTraceContext(activity.TraceId.ToString(), activity.SpanId.ToString());
            return new OtelSpan(activity, ticket);
        }
        catch
        {
            Backpressure.Release(ticket);
            throw;
        }
    }

    private static NoOpSpan DroppedSpan() =>
        new("00000000000000000000000000000000", "0000000000000000");
}

internal sealed class OtelSpan : ISpan
{
    private readonly Activity _activity;
    private readonly QueueTicket? _ticket;
    public OtelSpan(Activity activity, QueueTicket? ticket = null)
    {
        _activity = activity;
        _ticket = ticket;
    }
    public string TraceId => _activity.TraceId.ToString();
    public string SpanId => _activity.SpanId.ToString();
    public void SetAttribute(string key, object? value) => _activity.SetTag(key, value);
    public void RecordException(Exception ex) => _activity.AddException(ex);
    public void SetStatus(string status, string? description = null)
    {
        var s = status.Equals("ok", StringComparison.OrdinalIgnoreCase)
            ? ActivityStatusCode.Ok
            : ActivityStatusCode.Error;
        _activity.SetStatus(s, description);
    }
    public void Dispose()
    {
        _activity.Dispose();
        Backpressure.Release(_ticket);
    }
}

internal sealed class OtelMeter : IMeter
{
    private readonly Meter _meter;
    public OtelMeter(Meter meter) => _meter = meter;
    public ICounter CreateCounter(string name) => new OtelCounter(_meter.CreateCounter<long>(name), name);
    public IGauge CreateGauge(string name) => new OtelGauge(_meter.CreateGauge<double>(name), name);
    public IHistogram CreateHistogram(string name) => new OtelHistogram(_meter.CreateHistogram<double>(name), name);
}

internal sealed class OtelCounter : ICounter
{
    private readonly Counter<long> _c;
    private readonly string _name;
    private long _value;
    public OtelCounter(Counter<long> c, string name) { _c = c; _name = name; }
    public long Value => Interlocked.Read(ref _value);
    public void Add(long value, IReadOnlyDictionary<string, object?>? attributes = null)
    {
        // Live OTLP path must still honour enable + consent + sampling + backpressure.
        if (!Setup.IsMetricsEnabled()) return;
        if (!Consent.ShouldAllow(Signals.Metrics, "")) return;
        if (!Sampling.ShouldSample(Signals.Metrics, _name)) return;
        var ticket = Backpressure.TryAcquire(Signals.Metrics);
        if (ticket is null && Backpressure.GetQueuePolicy().MetricsMaxSize > 0) return;
        try
        {
            if (attributes is null || attributes.Count == 0)
            {
                _c.Add(value);
            }
            else
            {
                _c.Add(value, OtelTagHelper.ToTagList(attributes));
            }
            Interlocked.Add(ref _value, value);
            Health.RecordEmitted(Signals.Metrics);
        }
        finally
        {
            Backpressure.Release(ticket);
        }
    }
}

internal sealed class OtelGauge : IGauge
{
    private readonly Gauge<double> _g;
    private readonly string _name;
    private double _value;
    public OtelGauge(Gauge<double> g, string name) { _g = g; _name = name; }
    public double Value => _value;
    public void Set(double value, IReadOnlyDictionary<string, object?>? attributes = null)
    {
        if (!Setup.IsMetricsEnabled()) return;
        if (!Consent.ShouldAllow(Signals.Metrics, "")) return;
        if (!Sampling.ShouldSample(Signals.Metrics, _name)) return;
        var ticket = Backpressure.TryAcquire(Signals.Metrics);
        if (ticket is null && Backpressure.GetQueuePolicy().MetricsMaxSize > 0) return;
        try
        {
            if (attributes is null || attributes.Count == 0)
            {
                _g.Record(value);
            }
            else
            {
                _g.Record(value, OtelTagHelper.ToTagList(attributes));
            }
            _value = value;
            Health.RecordEmitted(Signals.Metrics);
        }
        finally
        {
            Backpressure.Release(ticket);
        }
    }
}

internal sealed class OtelHistogram : IHistogram
{
    private readonly Histogram<double> _h;
    private readonly string _name;
    private long _count;
    private double _sum;
    public OtelHistogram(Histogram<double> h, string name) { _h = h; _name = name; }
    public long Count => Interlocked.Read(ref _count);
    public double Sum => _sum;
    public void Record(double value, IReadOnlyDictionary<string, object?>? attributes = null)
    {
        if (!Setup.IsMetricsEnabled()) return;
        if (!Consent.ShouldAllow(Signals.Metrics, "")) return;
        if (!Sampling.ShouldSample(Signals.Metrics, _name)) return;
        var ticket = Backpressure.TryAcquire(Signals.Metrics);
        if (ticket is null && Backpressure.GetQueuePolicy().MetricsMaxSize > 0) return;
        try
        {
            if (attributes is null || attributes.Count == 0)
            {
                _h.Record(value);
            }
            else
            {
                _h.Record(value, OtelTagHelper.ToTagList(attributes));
            }
            Interlocked.Increment(ref _count);
            _sum += value;
            Health.RecordEmitted(Signals.Metrics);
        }
        finally
        {
            Backpressure.Release(ticket);
        }
    }
}

internal static class OtelTagHelper
{
    internal static TagList ToTagList(IReadOnlyDictionary<string, object?> attributes)
    {
        var tags = new TagList();
        foreach (var (key, value) in attributes)
        {
            tags.Add(key, value);
        }
        return tags;
    }
}

internal static class DateTimeOffsetExtensions
{
    public static long ToUnixTimeMicroseconds(this DateTimeOffset dto) =>
        dto.ToUnixTimeMilliseconds() * 1000;
}

/// <summary>Temporarily overrides process environment variables; restores on dispose.</summary>
internal sealed class EnvOverride : IDisposable
{
    private readonly List<(string Key, string? Previous)> _previous = new();

    public EnvOverride(params (string Key, string? Value)[] pairs)
    {
        foreach (var (key, value) in pairs)
        {
            _previous.Add((key, Environment.GetEnvironmentVariable(key)));
            Environment.SetEnvironmentVariable(key, value);
        }
    }

    public void Dispose()
    {
        foreach (var (key, prev) in _previous)
        {
            Environment.SetEnvironmentVariable(key, prev);
        }
    }
}
