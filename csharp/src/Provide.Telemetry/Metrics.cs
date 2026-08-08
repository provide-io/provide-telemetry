// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

public interface ICounter
{
    void Add(long value, IReadOnlyDictionary<string, object?>? attributes = null);
    long Value { get; }
}

public interface IGauge
{
    void Set(double value, IReadOnlyDictionary<string, object?>? attributes = null);
    double Value { get; }
}

public interface IHistogram
{
    void Record(double value, IReadOnlyDictionary<string, object?>? attributes = null);
    long Count { get; }
    double Sum { get; }
}

public interface IMeter
{
    ICounter CreateCounter(string name);
    IGauge CreateGauge(string name);
    IHistogram CreateHistogram(string name);
}

/// <summary>In-process counter used when no backend meter is installed.</summary>
public sealed class FallbackCounter : ICounter
{
    private readonly string _name;
    private long _value;

    public FallbackCounter(string name = "counter") => _name = name;

    public long Value => Interlocked.Read(ref _value);

    public void Add(long value, IReadOnlyDictionary<string, object?>? attributes = null)
    {
        var admission = SignalPipeline.Admit(Signals.Metrics, _name);
        if (!admission.Admitted) return;
        try
        {
            Interlocked.Add(ref _value, value);
            Health.RecordEmitted(Signals.Metrics);
        }
        finally
        {
            admission.Release();
        }
    }
}

/// <summary>In-process gauge used when no backend meter is installed.</summary>
public sealed class FallbackGauge : IGauge
{
    private readonly string _name;
    private readonly AtomicDouble _value = new();

    public FallbackGauge(string name = "gauge") => _name = name;

    public double Value => _value.Read();

    public void Set(double value, IReadOnlyDictionary<string, object?>? attributes = null)
    {
        var admission = SignalPipeline.Admit(Signals.Metrics, _name);
        if (!admission.Admitted) return;
        try
        {
            _value.Write(value);
            Health.RecordEmitted(Signals.Metrics);
        }
        finally
        {
            admission.Release();
        }
    }
}

/// <summary>In-process histogram used when no backend meter is installed.</summary>
public sealed class FallbackHistogram : IHistogram
{
    private readonly string _name;
    private readonly AtomicDouble _sum = new();
    private long _count;

    public FallbackHistogram(string name = "histogram") => _name = name;

    public long Count => Interlocked.Read(ref _count);

    public double Sum => _sum.Read();

    public void Record(double value, IReadOnlyDictionary<string, object?>? attributes = null)
    {
        var admission = SignalPipeline.Admit(Signals.Metrics, _name);
        if (!admission.Admitted) return;
        try
        {
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

public sealed class FallbackMeter : IMeter
{
    public ICounter CreateCounter(string name) => new FallbackCounter(name);
    public IGauge CreateGauge(string name) => new FallbackGauge(name);
    public IHistogram CreateHistogram(string name) => new FallbackHistogram(name);
}

public static class Metrics
{
    private static readonly FallbackMeter Fallback = new();

    public static IMeter GetMeter(string name = "")
    {
        Setup.EnsureLazyInit();
        return Setup.CurrentBackend?.GetMeter(name) ?? Fallback;
    }

    public static ICounter Counter(string name) => GetMeter().CreateCounter(name);
    public static IGauge Gauge(string name) => GetMeter().CreateGauge(name);
    public static IHistogram Histogram(string name) => GetMeter().CreateHistogram(name);
}
