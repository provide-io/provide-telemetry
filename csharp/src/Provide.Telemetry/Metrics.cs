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
    ICounter CreateCounter(string name, string? description = null, string? unit = null);
    IGauge CreateGauge(string name, string? description = null, string? unit = null);
    IHistogram CreateHistogram(string name, string? description = null, string? unit = null);
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

/// <remarks>
/// Description and unit are accepted for signature parity with the OTel meter
/// and dropped: the in-process instruments are never exported, so there is
/// nowhere for the metadata to go.
/// </remarks>
public sealed class FallbackMeter : IMeter
{
    public ICounter CreateCounter(string name, string? description = null, string? unit = null) =>
        new FallbackCounter(name);

    public IGauge CreateGauge(string name, string? description = null, string? unit = null) =>
        new FallbackGauge(name);

    public IHistogram CreateHistogram(string name, string? description = null, string? unit = null) =>
        new FallbackHistogram(name);
}

public static class Metrics
{
    private static readonly FallbackMeter Fallback = new();

    public static IMeter GetMeter(string name = "")
    {
        Setup.EnsureLazyInit();
        return Setup.CurrentBackend?.GetMeter(name) ?? Fallback;
    }

    public static ICounter Counter(string name, string? description = null, string? unit = null) =>
        GetMeter().CreateCounter(name, description, unit);

    public static IGauge Gauge(string name, string? description = null, string? unit = null) =>
        GetMeter().CreateGauge(name, description, unit);

    public static IHistogram Histogram(string name, string? description = null, string? unit = null) =>
        GetMeter().CreateHistogram(name, description, unit);

    /// <summary>Register <paramref name="callback"/> as a monotonic counter reporting cumulative totals.</summary>
    /// <remarks>
    /// Binds to the provider live now: created before setup, or with no
    /// provider, the callback never runs and the handle is inert.
    /// </remarks>
    public static ObservableInstrument ObservableCounter(
        string name, Func<IEnumerable<Observation>> callback, string? description = null, string? unit = null) =>
        GetMeter() is IObservableMeter meter
            ? meter.CreateObservableCounter(name, callback, description, unit)
            : new ObservableInstrument(name, callback);

    /// <summary>Register <paramref name="callback"/> as a gauge; a series it stops reporting disappears.</summary>
    public static ObservableInstrument ObservableGauge(
        string name, Func<IEnumerable<Observation>> callback, string? description = null, string? unit = null) =>
        GetMeter() is IObservableMeter meter
            ? meter.CreateObservableGauge(name, callback, description, unit)
            : new ObservableInstrument(name, callback);

    /// <summary>Register <paramref name="callback"/> as a non-monotonic sum.</summary>
    public static ObservableInstrument ObservableUpDownCounter(
        string name, Func<IEnumerable<Observation>> callback, string? description = null, string? unit = null) =>
        GetMeter() is IObservableMeter meter
            ? meter.CreateObservableUpDownCounter(name, callback, description, unit)
            : new ObservableInstrument(name, callback);
}
