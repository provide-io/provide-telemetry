// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

/// <summary>One value an observable instrument's callback reports.</summary>
public readonly record struct Observation(double Value, IReadOnlyDictionary<string, object?>? Attributes = null);

/// <summary>
/// A meter that can register observable (callback-reported) instruments.
/// </summary>
/// <remarks>
/// Separate from <see cref="IMeter"/> so a meter written against the original
/// interface keeps compiling. The in-process fallback does not implement it:
/// with no provider there is nothing to collect, so an observable created then
/// is never invoked (<c>prometheus_metrics.observable_instruments</c>).
/// </remarks>
public interface IObservableMeter
{
    ObservableInstrument CreateObservableCounter(
        string name, Func<IEnumerable<Observation>> callback, string? description = null, string? unit = null);

    ObservableInstrument CreateObservableGauge(
        string name, Func<IEnumerable<Observation>> callback, string? description = null, string? unit = null);

    ObservableInstrument CreateObservableUpDownCounter(
        string name, Func<IEnumerable<Observation>> callback, string? description = null, string? unit = null);
}

/// <summary>
/// A registered observable instrument; <see cref="Unregister"/> stops its callback.
/// </summary>
/// <remarks>
/// The callback runs at each collection — every scrape for Prometheus, every
/// export interval for OTLP — through <see cref="Collect"/>, which applies the
/// collection-time gates and isolates a failing callback.
/// </remarks>
public sealed class ObservableInstrument
{
    private readonly Func<IEnumerable<Observation>> _callback;
    private int _registered;
    private int _failures;

    public ObservableInstrument(string name, Func<IEnumerable<Observation>> callback)
    {
        Name = name ?? throw new ArgumentNullException(nameof(name));
        _callback = callback ?? throw new ArgumentNullException(nameof(callback));
    }

    public string Name { get; }

    /// <summary>Whether the callback is attached to a provider and not unregistered.</summary>
    public bool Registered => Volatile.Read(ref _registered) == 1;

    /// <summary>Stop the callback. Calling it again, or on an unattached instrument, is a no-op.</summary>
    public void Unregister() => Volatile.Write(ref _registered, 0);

    /// <summary>Mark the instrument as attached; called by the meter that registered it.</summary>
    public void Attach() => Volatile.Write(ref _registered, 1);

    /// <summary>
    /// Run one collection and return what the callback observed.
    /// </summary>
    /// <remarks>
    /// Nothing is observed once unregistered, while metrics are disabled, or
    /// while consent denies metrics. Observations are snapshots rather than
    /// events, so they are neither sampled nor given backpressure tickets. A
    /// callback that throws contributes nothing and logs one warning per
    /// instrument, never one per collection.
    /// </remarks>
    public IReadOnlyList<Observation> Collect()
    {
        if (!Registered || !Setup.IsMetricsEnabled() || !Consent.ShouldAllow(Signals.Metrics, "INFO"))
        {
            return [];
        }
        List<Observation> observations;
        try
        {
            observations = _callback().ToList();
        }
        catch (Exception ex)
        {
            WarnOnce(ex);
            return [];
        }
        foreach (var _ in observations) Health.RecordEmitted(Signals.Metrics);
        return observations;
    }

    private void WarnOnce(Exception ex)
    {
        if (Interlocked.Increment(ref _failures) != 1) return;
        Logging.GetLogger("provide.telemetry.metrics").Warning(
            "metrics.observable_callback_failed",
            new Dictionary<string, object?>(StringComparer.Ordinal)
            {
                ["instrument"] = Name,
                ["error"] = ex.Message,
            });
    }
}
