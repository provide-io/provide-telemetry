// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


namespace Provide.Telemetry;

public static class Resilience
{
    private static readonly object Gate = new();
    private static readonly Dictionary<string, ExporterPolicy> Policies = new(StringComparer.Ordinal)
    {
        [Signals.Logs] = new ExporterPolicy(),
        [Signals.Traces] = new ExporterPolicy(),
        [Signals.Metrics] = new ExporterPolicy(),
    };
    private static readonly Dictionary<string, CircuitState> Circuits = new(StringComparer.Ordinal)
    {
        [Signals.Logs] = new CircuitState(),
        [Signals.Traces] = new CircuitState(),
        [Signals.Metrics] = new CircuitState(),
    };

    public static void SetExporterPolicy(string signal, ExporterPolicy policy)
    {
        Signals.Validate(signal);
        lock (Gate)
        {
            Policies[signal] = new ExporterPolicy
            {
                Retries = Math.Max(0, policy.Retries),
                BackoffSeconds = Math.Max(0, policy.BackoffSeconds),
                TimeoutSeconds = Math.Max(0, policy.TimeoutSeconds),
                FailOpen = policy.FailOpen,
                AllowBlockingInEventLoop = policy.AllowBlockingInEventLoop,
            };
        }
    }

    public static ExporterPolicy GetExporterPolicy(string signal)
    {
        Signals.Validate(signal);
        lock (Gate)
        {
            var p = Policies.TryGetValue(signal, out var v) ? v : new ExporterPolicy();
            return new ExporterPolicy
            {
                Retries = p.Retries,
                BackoffSeconds = p.BackoffSeconds,
                TimeoutSeconds = p.TimeoutSeconds,
                FailOpen = p.FailOpen,
                AllowBlockingInEventLoop = p.AllowBlockingInEventLoop,
            };
        }
    }

    public static string GetCircuitState(string signal)
    {
        lock (Gate)
        {
            return Circuits.TryGetValue(signal, out var c) ? c.State : "closed";
        }
    }

    public static long GetCircuitOpenCount(string signal)
    {
        lock (Gate)
        {
            return Circuits.TryGetValue(signal, out var c) ? c.OpenCount : 0;
        }
    }

    internal static void Reset()
    {
        lock (Gate)
        {
            foreach (var k in new[] { Signals.Logs, Signals.Traces, Signals.Metrics })
            {
                Policies[k] = new ExporterPolicy();
                Circuits[k] = new CircuitState();
            }
        }
    }

    private sealed class CircuitState
    {
        public string State { get; set; } = "closed";
        public long OpenCount { get; set; }
    }
}
