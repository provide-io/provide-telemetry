// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


namespace Provide.Telemetry;

public static class Health
{
    private static long _logsEmitted, _logsDropped, _logsExportFailures, _logsRetries, _logsAsync;
    private static long _tracesEmitted, _tracesDropped, _tracesExportFailures, _tracesRetries, _tracesAsync;
    private static long _metricsEmitted, _metricsDropped, _metricsExportFailures, _metricsRetries, _metricsAsync;
    private static double _logsLatency, _tracesLatency, _metricsLatency;
    private static string _setupError = "";

    public static HealthSnapshot GetHealthSnapshot()
    {
        return new HealthSnapshot
        {
            LogsEmitted = Interlocked.Read(ref _logsEmitted),
            LogsDropped = Interlocked.Read(ref _logsDropped),
            LogsExportFailures = Interlocked.Read(ref _logsExportFailures),
            LogsRetries = Interlocked.Read(ref _logsRetries),
            LogsExportLatencyMs = _logsLatency,
            LogsAsyncBlockingRisk = Interlocked.Read(ref _logsAsync),
            LogsCircuitState = Resilience.GetCircuitState(Signals.Logs),
            LogsCircuitOpenCount = Resilience.GetCircuitOpenCount(Signals.Logs),

            TracesEmitted = Interlocked.Read(ref _tracesEmitted),
            TracesDropped = Interlocked.Read(ref _tracesDropped),
            TracesExportFailures = Interlocked.Read(ref _tracesExportFailures),
            TracesRetries = Interlocked.Read(ref _tracesRetries),
            TracesExportLatencyMs = _tracesLatency,
            TracesAsyncBlockingRisk = Interlocked.Read(ref _tracesAsync),
            TracesCircuitState = Resilience.GetCircuitState(Signals.Traces),
            TracesCircuitOpenCount = Resilience.GetCircuitOpenCount(Signals.Traces),

            MetricsEmitted = Interlocked.Read(ref _metricsEmitted),
            MetricsDropped = Interlocked.Read(ref _metricsDropped),
            MetricsExportFailures = Interlocked.Read(ref _metricsExportFailures),
            MetricsRetries = Interlocked.Read(ref _metricsRetries),
            MetricsExportLatencyMs = _metricsLatency,
            MetricsAsyncBlockingRisk = Interlocked.Read(ref _metricsAsync),
            MetricsCircuitState = Resilience.GetCircuitState(Signals.Metrics),
            MetricsCircuitOpenCount = Resilience.GetCircuitOpenCount(Signals.Metrics),

            SetupError = Volatile.Read(ref _setupError) ?? "",
        };
    }

    internal static void RecordEmitted(string signal)
    {
        switch (signal)
        {
            case Signals.Logs: Interlocked.Increment(ref _logsEmitted); break;
            case Signals.Traces: Interlocked.Increment(ref _tracesEmitted); break;
            case Signals.Metrics: Interlocked.Increment(ref _metricsEmitted); break;
        }
    }

    internal static void RecordDropped(string signal)
    {
        switch (signal)
        {
            case Signals.Logs: Interlocked.Increment(ref _logsDropped); break;
            case Signals.Traces: Interlocked.Increment(ref _tracesDropped); break;
            case Signals.Metrics: Interlocked.Increment(ref _metricsDropped); break;
        }
    }

    internal static void SetSetupError(string error) => Volatile.Write(ref _setupError, error ?? "");

    internal static void Reset()
    {
        Interlocked.Exchange(ref _logsEmitted, 0);
        Interlocked.Exchange(ref _logsDropped, 0);
        Interlocked.Exchange(ref _logsExportFailures, 0);
        Interlocked.Exchange(ref _logsRetries, 0);
        Interlocked.Exchange(ref _logsAsync, 0);
        Interlocked.Exchange(ref _tracesEmitted, 0);
        Interlocked.Exchange(ref _tracesDropped, 0);
        Interlocked.Exchange(ref _tracesExportFailures, 0);
        Interlocked.Exchange(ref _tracesRetries, 0);
        Interlocked.Exchange(ref _tracesAsync, 0);
        Interlocked.Exchange(ref _metricsEmitted, 0);
        Interlocked.Exchange(ref _metricsDropped, 0);
        Interlocked.Exchange(ref _metricsExportFailures, 0);
        Interlocked.Exchange(ref _metricsRetries, 0);
        Interlocked.Exchange(ref _metricsAsync, 0);
        _logsLatency = _tracesLatency = _metricsLatency = 0;
        Volatile.Write(ref _setupError, "");
    }
}
