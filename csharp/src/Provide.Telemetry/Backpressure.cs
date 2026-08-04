// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


namespace Provide.Telemetry;

public static class Backpressure
{
    private static readonly object Gate = new();
    private static QueuePolicy _policy = new();
    private static int _logsCount;
    private static int _tracesCount;
    private static int _metricsCount;

    public static void SetQueuePolicy(QueuePolicy policy)
    {
        lock (Gate)
        {
            _policy = new QueuePolicy
            {
                LogsMaxSize = Math.Max(0, policy.LogsMaxSize),
                TracesMaxSize = Math.Max(0, policy.TracesMaxSize),
                MetricsMaxSize = Math.Max(0, policy.MetricsMaxSize),
            };
            _logsCount = 0;
            _tracesCount = 0;
            _metricsCount = 0;
        }
    }

    public static QueuePolicy GetQueuePolicy()
    {
        lock (Gate)
        {
            return new QueuePolicy
            {
                LogsMaxSize = _policy.LogsMaxSize,
                TracesMaxSize = _policy.TracesMaxSize,
                MetricsMaxSize = _policy.MetricsMaxSize,
            };
        }
    }

    public static QueueTicket? TryAcquire(string signal)
    {
        lock (Gate)
        {
            var (max, count) = signal switch
            {
                Signals.Logs => (_policy.LogsMaxSize, _logsCount),
                Signals.Traces => (_policy.TracesMaxSize, _tracesCount),
                Signals.Metrics => (_policy.MetricsMaxSize, _metricsCount),
                _ => (-1, 0),
            };
            if (max < 0) return null;
            // 0 means unlimited
            if (max == 0 || count < max)
            {
                switch (signal)
                {
                    case Signals.Logs: _logsCount++; break;
                    case Signals.Traces: _tracesCount++; break;
                    case Signals.Metrics: _metricsCount++; break;
                }
                return new QueueTicket(signal);
            }
            Health.RecordDropped(signal);
            return null;
        }
    }

    public static void Release(QueueTicket? ticket)
    {
        if (ticket is null || ticket.Released) return;
        lock (Gate)
        {
            if (ticket.Released) return;
            ticket.Released = true;
            switch (ticket.Signal)
            {
                case Signals.Logs when _logsCount > 0: _logsCount--; break;
                case Signals.Traces when _tracesCount > 0: _tracesCount--; break;
                case Signals.Metrics when _metricsCount > 0: _metricsCount--; break;
            }
        }
    }

    internal static void Reset()
    {
        lock (Gate)
        {
            _policy = new QueuePolicy();
            _logsCount = _tracesCount = _metricsCount = 0;
        }
    }
}

public sealed class QueueTicket
{
    internal QueueTicket(string signal) { Signal = signal; }
    public string Signal { get; }
    internal bool Released { get; set; }
}
