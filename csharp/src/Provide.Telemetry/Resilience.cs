// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Diagnostics;

namespace Provide.Telemetry;

/// <summary>How an export call ended.</summary>
public enum ExportOutcome
{
    /// <summary>An attempt reported success.</summary>
    Succeeded,

    /// <summary>Every permitted attempt ran and none succeeded.</summary>
    Failed,

    /// <summary>The deadline expired before another attempt could run.</summary>
    TimedOut,
}

/// <summary>The result of one <see cref="ResilienceExecutor.ExecuteAsync"/> call.</summary>
/// <param name="Outcome">How the call ended.</param>
/// <param name="Attempts">Attempts actually executed.</param>
public readonly record struct ExportAttemptResult(ExportOutcome Outcome, int Attempts)
{
    /// <summary>True when an attempt reported success.</summary>
    public bool Succeeded => Outcome == ExportOutcome.Succeeded;

    public static ExportAttemptResult Success(int attempts) => new(ExportOutcome.Succeeded, attempts);

    public static ExportAttemptResult Failed(int attempts) => new(ExportOutcome.Failed, attempts);

    public static ExportAttemptResult TimedOut(int attempts) => new(ExportOutcome.TimedOut, attempts);
}

public static class Resilience
{
    /// <summary>
    /// Hard ceiling on export attempts (1 initial + 100 retries), shared with the
    /// Python/TypeScript/Go/Rust runtimes.
    /// </summary>
    public const int MaxExportAttempts = 101;

    /// <summary>Consecutive timeouts before the breaker trips.</summary>
    internal const int CircuitBreakerThreshold = 3;

    /// <summary>Seconds before a tripped breaker allows a half-open probe.</summary>
    internal const double CircuitBaseCooldownSeconds = 30.0;

    /// <summary>Upper bound on the exponential cooldown.</summary>
    internal const double CircuitMaxCooldownSeconds = 1024.0;

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

    /// <summary>
    /// Install the export policy for a signal.
    /// </summary>
    /// <remarks>
    /// Retries are clamped to <see cref="MaxExportAttempts"/> - 1 here as well as
    /// rejected in <c>ConfigEnv.ValidateRetries</c>: a caller reaching this API
    /// directly bypasses config validation entirely, and a policy asking for a
    /// million attempts would otherwise be stored verbatim.
    /// </remarks>
    public static void SetExporterPolicy(string signal, ExporterPolicy policy)
    {
        Signals.Validate(signal);
        ArgumentNullException.ThrowIfNull(policy);
        lock (Gate)
        {
            Policies[signal] = new ExporterPolicy
            {
                Retries = Math.Clamp(policy.Retries, 0, MaxExportAttempts - 1),
                BackoffSeconds = Math.Max(0, policy.BackoffSeconds),
                TimeoutSeconds = Math.Max(0, policy.TimeoutSeconds),
                FailOpen = policy.FailOpen,
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
            };
        }
    }

    /// <summary>Current breaker state: closed, open, or half_open.</summary>
    public static string GetCircuitState(string signal)
    {
        lock (Gate)
        {
            return Circuits.TryGetValue(signal, out var c) ? c.Describe() : CircuitState.Closed;
        }
    }

    public static long GetCircuitOpenCount(string signal)
    {
        lock (Gate)
        {
            return Circuits.TryGetValue(signal, out var c) ? c.OpenCount : 0;
        }
    }

    internal static bool AllowAttempt(string signal)
    {
        lock (Gate)
        {
            return !Circuits.TryGetValue(signal, out var c) || c.AllowAttempt();
        }
    }

    internal static void RecordSuccess(string signal)
    {
        lock (Gate)
        {
            if (Circuits.TryGetValue(signal, out var c)) c.RecordSuccess();
        }
    }

    internal static void RecordFailure(string signal, bool isTimeout)
    {
        lock (Gate)
        {
            if (Circuits.TryGetValue(signal, out var c)) c.RecordFailure(isTimeout);
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

    /// <summary>
    /// Per-signal breaker: trips on consecutive timeouts, decays through a probe.
    /// </summary>
    /// <remarks>
    /// Only timeouts count toward tripping, and any other failure resets the
    /// run — the breaker exists to shed load from a saturated exporter pool, and
    /// a collector returning 4xx immediately is not saturating anything. This
    /// mirrors <c>_record_attempt_failure</c> in <c>src/provide/telemetry/resilience.py</c>.
    /// </remarks>
    private sealed class CircuitState
    {
        public const string Closed = "closed";
        public const string Open = "open";
        public const string HalfOpen = "half_open";

        private int _consecutiveTimeouts;
        private bool _halfOpenProbing;
        private long _trippedAtTicks;

        public long OpenCount { get; private set; }

        public string Describe()
        {
            if (_halfOpenProbing) return HalfOpen;
            if (_consecutiveTimeouts < CircuitBreakerThreshold) return Closed;
            return CooldownRemaining() > TimeSpan.Zero ? Open : HalfOpen;
        }

        public bool AllowAttempt()
        {
            if (_consecutiveTimeouts < CircuitBreakerThreshold) return true;
            // A probe is already in flight: a second caller would turn the single
            // trial balloon into a thundering herd against a collector that has
            // not yet proved it recovered.
            if (_halfOpenProbing) return false;
            if (CooldownRemaining() > TimeSpan.Zero) return false;
            _halfOpenProbing = true;
            return true;
        }

        public void RecordSuccess()
        {
            if (_halfOpenProbing)
            {
                _halfOpenProbing = false;
                _consecutiveTimeouts = 0;
                // Decay rather than reset: the cooldown is exponential in
                // OpenCount, so one good probe shortens the next wait instead of
                // erasing the history of an exporter that keeps failing.
                OpenCount = Math.Max(0, OpenCount - 1);
                return;
            }
            _consecutiveTimeouts = 0;
        }

        public void RecordFailure(bool isTimeout)
        {
            if (_halfOpenProbing)
            {
                _halfOpenProbing = false;
                Trip();
                return;
            }
            if (!isTimeout)
            {
                _consecutiveTimeouts = 0;
                return;
            }
            _consecutiveTimeouts++;
            if (_consecutiveTimeouts >= CircuitBreakerThreshold) Trip();
        }

        private void Trip()
        {
            OpenCount++;
            _trippedAtTicks = Stopwatch.GetTimestamp();
        }

        private TimeSpan CooldownRemaining()
        {
            var cooldown = Math.Min(
                CircuitBaseCooldownSeconds * Math.Pow(2, OpenCount), CircuitMaxCooldownSeconds);
            var elapsed = Stopwatch.GetElapsedTime(_trippedAtTicks);
            return TimeSpan.FromSeconds(cooldown) - elapsed;
        }
    }
}
