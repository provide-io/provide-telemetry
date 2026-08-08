// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Diagnostics;
using System.Diagnostics.Metrics;

using Provide.Telemetry;

namespace Provide.Telemetry.OpenTelemetry;

internal sealed class OtelTracer : ITracer
{
    private readonly ActivitySource _source;

    public OtelTracer(ActivitySource source, string name)
    {
        _source = source;
        _ = name;
    }

    public ISpan StartSpan(string name)
    {
        // Probabilistic sampling is delegated to the SDK's ParentBased /
        // TraceIdRatioBased sampler so a span is not sampled twice; consent and
        // backpressure still apply here, as they do on the fallback path.
        var admission = SignalPipeline.Admit(Signals.Traces, name, sample: false);
        if (!admission.Admitted) return NoOpSpan.Dropped();

        try
        {
            var activity = _source.StartActivity(name, ActivityKind.Internal);
            if (activity is null)
            {
                admission.Release();
                return NoOpSpan.Dropped();
            }
            Health.RecordEmitted(Signals.Traces);
            var scope = Context.PushTraceContext(activity.TraceId.ToString(), activity.SpanId.ToString());
            return new OtelSpan(activity, admission, scope);
        }
        catch
        {
            admission.Release();
            throw;
        }
    }
}

internal sealed class OtelSpan : ISpan
{
    private readonly Activity _activity;
    private readonly SignalAdmission _admission;
    private readonly IDisposable _contextScope;
    private int _disposed;

    public OtelSpan(Activity activity, SignalAdmission admission, IDisposable contextScope)
    {
        _activity = activity;
        _admission = admission;
        _contextScope = contextScope;
    }

    public string TraceId => _activity.TraceId.ToString();
    public string SpanId => _activity.SpanId.ToString();
    public void SetAttribute(string key, object? value) => _activity.SetTag(key, value);
    public void RecordException(Exception ex) => _activity.AddException(ex);

    public void SetStatus(string status, string? description = null) =>
        _activity.SetStatus(
            status.Equals("ok", StringComparison.OrdinalIgnoreCase)
                ? ActivityStatusCode.Ok
                : ActivityStatusCode.Error,
            description);

    /// <summary>
    /// End the span, restore the enclosing trace context, and return the ticket.
    /// </summary>
    /// <remarks>
    /// Idempotent: a double dispose — from an explicit call inside a
    /// <c>using</c>, say — must not release a second queue ticket or roll the
    /// context back past the span that actually owns it.
    /// </remarks>
    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0) return;
        _activity.Dispose();
        _contextScope.Dispose();
        _admission.Release();
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
    private readonly Counter<long> _counter;
    private readonly string _name;
    private long _value;

    public OtelCounter(Counter<long> counter, string name)
    {
        _counter = counter;
        _name = name;
    }

    public long Value => Interlocked.Read(ref _value);

    public void Add(long value, IReadOnlyDictionary<string, object?>? attributes = null)
    {
        // The live OTLP path runs the same admission ladder as the fallback:
        // a metric that consent or sampling rejected must not reach a collector
        // just because an exporter happens to be installed.
        var admission = SignalPipeline.Admit(Signals.Metrics, _name);
        if (!admission.Admitted) return;
        try
        {
            _counter.Add(value, OtelTagHelper.ToTagList(attributes));
            Interlocked.Add(ref _value, value);
            Health.RecordEmitted(Signals.Metrics);
        }
        finally
        {
            admission.Release();
        }
    }
}

internal sealed class OtelGauge : IGauge
{
    private readonly Gauge<double> _gauge;
    private readonly string _name;
    private readonly AtomicDouble _value = new();

    public OtelGauge(Gauge<double> gauge, string name)
    {
        _gauge = gauge;
        _name = name;
    }

    public double Value => _value.Read();

    public void Set(double value, IReadOnlyDictionary<string, object?>? attributes = null)
    {
        var admission = SignalPipeline.Admit(Signals.Metrics, _name);
        if (!admission.Admitted) return;
        try
        {
            _gauge.Record(value, OtelTagHelper.ToTagList(attributes));
            _value.Write(value);
            Health.RecordEmitted(Signals.Metrics);
        }
        finally
        {
            admission.Release();
        }
    }
}

internal sealed class OtelHistogram : IHistogram
{
    private readonly Histogram<double> _histogram;
    private readonly string _name;
    private readonly AtomicDouble _sum = new();
    private long _count;

    public OtelHistogram(Histogram<double> histogram, string name)
    {
        _histogram = histogram;
        _name = name;
    }

    public long Count => Interlocked.Read(ref _count);
    public double Sum => _sum.Read();

    public void Record(double value, IReadOnlyDictionary<string, object?>? attributes = null)
    {
        var admission = SignalPipeline.Admit(Signals.Metrics, _name);
        if (!admission.Admitted) return;
        try
        {
            _histogram.Record(value, OtelTagHelper.ToTagList(attributes));
            Interlocked.Increment(ref _count);
            _sum.Add(value);
            Health.RecordEmitted(Signals.Metrics);
        }
        finally
        {
            admission.Release();
        }
    }
}

internal static class OtelTagHelper
{
    internal static TagList ToTagList(IReadOnlyDictionary<string, object?>? attributes)
    {
        var tags = new TagList();
        if (attributes is null) return tags;
        foreach (var (key, value) in attributes) tags.Add(key, value);
        return tags;
    }
}
