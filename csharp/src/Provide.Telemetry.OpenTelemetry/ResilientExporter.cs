// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;

namespace Provide.Telemetry.OpenTelemetry;

/// <summary>
/// Connects the configured exporter policy to a real OTLP export attempt.
/// </summary>
/// <remarks>
/// Before this existed, <c>PROVIDE_EXPORTER_*_RETRIES</c>, the backoff, the
/// timeout and the circuit breaker were all parsed, stored, reported by
/// <c>GetExporterPolicy</c> — and never consulted by anything that talked to a
/// collector. The policy is applied here, on the only call this SDK makes that
/// can actually fail against the network: the provider's force-flush.
/// </remarks>
internal static class ResilientExporter
{
    /// <summary>
    /// Run one signal's drain under its exporter policy.
    /// </summary>
    /// <remarks>
    /// The drain is dispatched to the thread pool because
    /// <c>ForceFlush</c> blocks; running it inline would serialize the drains
    /// that <see cref="ProviderDrains"/> means to overlap.
    /// </remarks>
    public static Task<ExportAttemptResult> DrainAsync(ProviderDrain drain, DateTimeOffset deadline) =>
        Task.Run(async () => await ResilienceExecutor.ExecuteAsync(
            drain.Signal,
            _ => new ValueTask<bool>(drain.ForceFlush(BudgetMilliseconds(deadline))),
            deadline).ConfigureAwait(false));

    /// <summary>
    /// The per-attempt millisecond budget left before the shared deadline.
    /// </summary>
    /// <remarks>
    /// <c>ForceFlush</c> treats a non-positive timeout as "return immediately",
    /// so an expired deadline still yields a real (if instant) attempt rather
    /// than an unbounded one — the ceiling is clamped into int range because the
    /// SDK's overload takes milliseconds as <see cref="int"/>.
    /// </remarks>
    private static int BudgetMilliseconds(DateTimeOffset deadline)
    {
        var remaining = (deadline - DateTimeOffset.UtcNow).TotalMilliseconds;
        return (int)Math.Clamp(remaining, 0, int.MaxValue);
    }
}
