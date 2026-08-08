// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

/// <summary>Which signals a backend actually installed a provider for.</summary>
public readonly record struct ProviderFlags(bool Logs, bool Traces, bool Metrics)
{
    /// <summary>No provider installed for any signal.</summary>
    public static ProviderFlags None => default;

    /// <summary>True when at least one signal has a live provider.</summary>
    public bool Any => Logs || Traces || Metrics;
}

/// <summary>
/// The seam between the OTel-free core and an exporter integration.
/// </summary>
/// <remarks>
/// Core owns admission control, hardening, local rendering and health; a backend
/// owns nothing but delivery. The interface is expressed entirely in core types
/// so <c>Provide.Telemetry</c> can reference only the BCL: an application that
/// wants no OpenTelemetry dependency installs the core package alone and every
/// facade call still works against the in-process fallbacks.
/// </remarks>
public interface ITelemetryBackend : IDisposable
{
    /// <summary>Signals this backend installed an owned provider for.</summary>
    ProviderFlags Providers { get; }

    /// <summary>A backend tracer, or null to fall back to the core no-op tracer.</summary>
    ITracer? GetTracer(string name);

    /// <summary>A backend meter, or null to fall back to the core in-process meter.</summary>
    IMeter? GetMeter(string name);

    /// <summary>Deliver one already-hardened record. Must not throw.</summary>
    void EmitLog(CanonicalLogRecord record);

    /// <summary>Drain every owned signal against one absolute deadline.</summary>
    FlushResult Flush(DateTimeOffset deadline);

    /// <summary>Drain and tear down every owned provider against one absolute deadline.</summary>
    void Shutdown(DateTimeOffset deadline);
}

/// <summary>
/// Process-wide registration point for the backend factory.
/// </summary>
/// <remarks>
/// Registration is explicit rather than reflective. Core deliberately holds no
/// name of the integration assembly: a reflective probe would make the core
/// package fail differently depending on what happens to be on the probing
/// application's load path, and would defeat trimming.
/// </remarks>
public static class TelemetryBackendRegistry
{
    private static Func<TelemetryConfig, ITelemetryBackend>? _factory;
    private static int _hostLogs;
    private static int _hostTraces;
    private static int _hostMetrics;

    /// <summary>Install the factory used for every subsequent lifecycle start.</summary>
    public static void Register(Func<TelemetryConfig, ITelemetryBackend> factory) =>
        Volatile.Write(ref _factory, factory ?? throw new ArgumentNullException(nameof(factory)));

    /// <summary>True when an integration package has registered a factory.</summary>
    public static bool IsRegistered => Volatile.Read(ref _factory) is not null;

    /// <summary>
    /// Record that the host application installed its own providers.
    /// </summary>
    /// <remarks>
    /// Adoption is reported, never drained: a host's batch processor is not ours
    /// to force-flush, so a flush of an adopted signal answers <c>NotOwned</c>
    /// rather than claiming success. Marks survive our own provider teardown —
    /// the host's providers outlive our lifecycle.
    /// </remarks>
    public static void MarkHostProviders(bool traces = false, bool metrics = false, bool logs = false)
    {
        Volatile.Write(ref _hostTraces, traces ? 1 : 0);
        Volatile.Write(ref _hostMetrics, metrics ? 1 : 0);
        Volatile.Write(ref _hostLogs, logs ? 1 : 0);
    }

    /// <summary>Forget every host-adoption mark.</summary>
    public static void ClearHostProviders() => MarkHostProviders();

    /// <summary>Host-installed providers, as last marked.</summary>
    public static ProviderFlags HostProviders => new(
        Volatile.Read(ref _hostLogs) == 1,
        Volatile.Read(ref _hostTraces) == 1,
        Volatile.Read(ref _hostMetrics) == 1);

    internal static ITelemetryBackend? Create(TelemetryConfig config) =>
        Volatile.Read(ref _factory)?.Invoke(config);
}

/// <summary>Flush results for signals nothing owned drained.</summary>
internal static class FlushResults
{
    /// <summary>
    /// Build the result for a flush where no owned provider ran.
    /// </summary>
    /// <remarks>
    /// <c>NotOwned</c> and <c>NotInstalled</c> are different answers on purpose:
    /// a caller flushing before a freeze must be able to tell "there was nothing
    /// to drain" from "records may still sit in the host's batch processor".
    /// </remarks>
    public static FlushResult Undrained(ProviderFlags owned, ProviderFlags host) => new()
    {
        Logs = Signal(owned.Logs, host.Logs),
        Traces = Signal(owned.Traces, host.Traces),
        Metrics = Signal(owned.Metrics, host.Metrics),
    };

    public static SignalFlushResult Signal(bool owned, bool host) => new()
    {
        NotInstalled = !owned && !host,
        NotOwned = !owned && host,
    };
}
