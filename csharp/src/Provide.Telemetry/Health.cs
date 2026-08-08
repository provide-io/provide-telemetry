// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

/// <summary>Self-observability counters for the three signals.</summary>
/// <remarks>
/// The snapshot layout is the cross-language contract in
/// <c>spec/behavioral_fixtures.yaml</c>: eight per-signal fields across three
/// signals plus two global ones.
/// </remarks>
public static class Health
{
    private sealed class SignalCounters
    {
        public long Emitted;
        public long Dropped;
        public long ExportFailures;
        public long Retries;
        public long AsyncBlockingRisk;
        public readonly AtomicDouble LatencyMs = new();

        public void Reset()
        {
            Interlocked.Exchange(ref Emitted, 0);
            Interlocked.Exchange(ref Dropped, 0);
            Interlocked.Exchange(ref ExportFailures, 0);
            Interlocked.Exchange(ref Retries, 0);
            Interlocked.Exchange(ref AsyncBlockingRisk, 0);
            LatencyMs.Reset();
        }
    }

    private static readonly SignalCounters LogsCounters = new();
    private static readonly SignalCounters TracesCounters = new();
    private static readonly SignalCounters MetricsCounters = new();
    private static long _receiptFailures;
    private static string _setupError = "";

    public static HealthSnapshot GetHealthSnapshot()
    {
        return new HealthSnapshot
        {
            LogsEmitted = Interlocked.Read(ref LogsCounters.Emitted),
            LogsDropped = Interlocked.Read(ref LogsCounters.Dropped),
            LogsExportFailures = Interlocked.Read(ref LogsCounters.ExportFailures),
            LogsRetries = Interlocked.Read(ref LogsCounters.Retries),
            LogsExportLatencyMs = LogsCounters.LatencyMs.Read(),
            LogsAsyncBlockingRisk = Interlocked.Read(ref LogsCounters.AsyncBlockingRisk),
            LogsCircuitState = Resilience.GetCircuitState(Signals.Logs),
            LogsCircuitOpenCount = Resilience.GetCircuitOpenCount(Signals.Logs),

            TracesEmitted = Interlocked.Read(ref TracesCounters.Emitted),
            TracesDropped = Interlocked.Read(ref TracesCounters.Dropped),
            TracesExportFailures = Interlocked.Read(ref TracesCounters.ExportFailures),
            TracesRetries = Interlocked.Read(ref TracesCounters.Retries),
            TracesExportLatencyMs = TracesCounters.LatencyMs.Read(),
            TracesAsyncBlockingRisk = Interlocked.Read(ref TracesCounters.AsyncBlockingRisk),
            TracesCircuitState = Resilience.GetCircuitState(Signals.Traces),
            TracesCircuitOpenCount = Resilience.GetCircuitOpenCount(Signals.Traces),

            MetricsEmitted = Interlocked.Read(ref MetricsCounters.Emitted),
            MetricsDropped = Interlocked.Read(ref MetricsCounters.Dropped),
            MetricsExportFailures = Interlocked.Read(ref MetricsCounters.ExportFailures),
            MetricsRetries = Interlocked.Read(ref MetricsCounters.Retries),
            MetricsExportLatencyMs = MetricsCounters.LatencyMs.Read(),
            MetricsAsyncBlockingRisk = Interlocked.Read(ref MetricsCounters.AsyncBlockingRisk),
            MetricsCircuitState = Resilience.GetCircuitState(Signals.Metrics),
            MetricsCircuitOpenCount = Resilience.GetCircuitOpenCount(Signals.Metrics),

            ReceiptFailures = Interlocked.Read(ref _receiptFailures),
            SetupError = Volatile.Read(ref _setupError) ?? "",
        };
    }

    internal static void RecordEmitted(string signal) =>
        Interlocked.Increment(ref For(signal).Emitted);

    internal static void RecordDropped(string signal) =>
        Interlocked.Increment(ref For(signal).Dropped);

    internal static void RecordExportFailure(string signal) =>
        Interlocked.Increment(ref For(signal).ExportFailures);

    internal static void IncrementRetries(string signal) =>
        Interlocked.Increment(ref For(signal).Retries);

    /// <summary>
    /// Record the wall-clock cost of one export attempt.
    /// </summary>
    /// <remarks>
    /// Last-writer-wins rather than an average: the field answers "how slow is
    /// the collector right now", which a running mean would smear across an
    /// outage that has already ended.
    /// </remarks>
    internal static void RecordAttempt(string signal, TimeSpan elapsed) =>
        For(signal).LatencyMs.Write(elapsed.TotalMilliseconds);

    /// <summary>
    /// Count a receipt the sink refused or faulted on.
    /// </summary>
    /// <remarks>
    /// A counter is the whole reporting channel for a failed receipt on purpose:
    /// logging one would run the logger, which runs redaction, which produces a
    /// receipt, which fails again. See <see cref="Receipts.Emit"/>.
    /// </remarks>
    internal static void RecordReceiptFailure() => Interlocked.Increment(ref _receiptFailures);

    internal static void SetSetupError(string error) => Volatile.Write(ref _setupError, error ?? "");

    internal static void Reset()
    {
        LogsCounters.Reset();
        TracesCounters.Reset();
        MetricsCounters.Reset();
        Interlocked.Exchange(ref _receiptFailures, 0);
        Volatile.Write(ref _setupError, "");
    }

    private static SignalCounters For(string signal) => signal switch
    {
        Signals.Traces => TracesCounters,
        Signals.Metrics => MetricsCounters,
        _ => LogsCounters,
    };
}
