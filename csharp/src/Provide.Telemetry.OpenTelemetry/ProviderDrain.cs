// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;

namespace Provide.Telemetry.OpenTelemetry;

/// <summary>One signal's blocking force-flush, named by its signal.</summary>
/// <param name="Signal">Canonical signal name — logs, traces or metrics.</param>
/// <param name="ForceFlush">
/// Drains the provider, given a millisecond budget; returns whether it emptied.
/// </param>
internal sealed record ProviderDrain(string Signal, Func<int, bool> ForceFlush);

/// <summary>Runs every provider drain against one shared absolute deadline.</summary>
internal static class ProviderDrains
{
    /// <summary>
    /// Start every drain together and wait for all of them within the deadline.
    /// </summary>
    /// <remarks>
    /// Draining sequentially would multiply the caller's budget by the number of
    /// installed signals: three providers, each handed "the timeout", turns a
    /// one-second <c>Shutdown</c> into three seconds against an unreachable
    /// collector. Here the deadline is absolute and shared, so the wall-clock
    /// cost of the whole operation is the deadline, not a multiple of it.
    /// <para>
    /// A drain that is still running when the deadline passes is abandoned, not
    /// cancelled: <c>ForceFlush</c> already took a millisecond budget of its own
    /// and will return on its own. Blocking longer to observe that would defeat
    /// the deadline this function exists to honor.
    /// </para>
    /// </remarks>
    public static void Run(IReadOnlyList<ProviderDrain> drains, DateTimeOffset deadline, FlushResult result)
    {
        if (drains.Count == 0) return;

        var running = drains
            .Select(drain => (drain.Signal, Task: ResilientExporter.DrainAsync(drain, deadline)))
            .ToArray();

        RecordBlockingRisk(drains);

        var budget = deadline - DateTimeOffset.UtcNow;
        // Task.WhenAll cannot be waited with a negative TimeSpan, and an expired
        // deadline still has one in-flight attempt per signal by contract, so a
        // spent budget waits zero rather than throwing.
        var wait = budget > TimeSpan.Zero ? budget : TimeSpan.Zero;
        Task.WhenAll(running.Select(r => r.Task)).Wait(wait);

        foreach (var (signal, task) in running)
        {
            Apply(result, signal, task);
        }
    }

    /// <summary>
    /// Record, per signal, that this drain is about to park the caller's thread.
    /// </summary>
    /// <remarks>
    /// The <c>Wait</c> above is synchronous by design — <c>FlushTelemetry</c> and
    /// <c>ShutdownTelemetry</c> are synchronous APIs — and blocking is harmless
    /// on a pool thread. It is not harmless on a thread carrying a
    /// <see cref="SynchronizationContext"/>: a UI message pump or a classic
    /// ASP.NET request thread parked here is the .NET shape of the asyncio
    /// hazard <c>async_blocking_risk_*</c> exists to count. The check is made on
    /// the calling thread, before the wait, because that is the only thread
    /// whose context is the caller's.
    /// </remarks>
    private static void RecordBlockingRisk(IReadOnlyList<ProviderDrain> drains)
    {
        if (SynchronizationContext.Current is null) return;
        foreach (var drain in drains)
        {
            Health.IncrementAsyncBlockingRisk(drain.Signal);
        }
    }

    private static void Apply(FlushResult result, string signal, Task<ExportAttemptResult> task)
    {
        var target = signal switch
        {
            Signals.Traces => result.Traces,
            Signals.Metrics => result.Metrics,
            _ => result.Logs,
        };

        if (!task.IsCompletedSuccessfully)
        {
            // Still running at the deadline, or faulted on a path ExecuteAsync
            // does not swallow: either way nothing confirmed the drain emptied.
            target.TimedOut = true;
            return;
        }

        var outcome = task.Result;
        target.Flushed = outcome.Succeeded;
        target.TimedOut = outcome.Outcome == ExportOutcome.TimedOut;
        target.Failed = outcome.Outcome == ExportOutcome.Failed;
    }
}
