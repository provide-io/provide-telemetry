// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Diagnostics;

namespace Provide.Telemetry;

/// <summary>
/// Runs one export under its signal's policy: breaker, retries, backoff, deadline.
/// </summary>
/// <remarks>
/// This is the only place the exporter policy becomes behavior. It lives in core
/// rather than the OpenTelemetry package because the policy, the breaker and the
/// health counters are core state; the integration supplies nothing but the
/// attempt delegate.
/// </remarks>
public static class ResilienceExecutor
{
    /// <summary>
    /// Execute <paramref name="attempt"/> until it succeeds, the attempt ceiling
    /// is reached, or the deadline passes.
    /// </summary>
    /// <remarks>
    /// Never throws for a failed export. Flush and shutdown call this on the way
    /// out of a process; a collector that is down must produce a result, not an
    /// exception at a caller who is trying to exit.
    /// </remarks>
    /// <param name="signal">Canonical signal name.</param>
    /// <param name="attempt">Returns whether the export succeeded.</param>
    /// <param name="deadline">Absolute deadline shared by every drain in this operation.</param>
    /// <param name="cancellationToken">Caller cancellation; propagates.</param>
    public static async ValueTask<ExportAttemptResult> ExecuteAsync(
        string signal,
        Func<CancellationToken, ValueTask<bool>> attempt,
        DateTimeOffset deadline,
        CancellationToken cancellationToken = default)
    {
        Signals.Validate(signal);
        ArgumentNullException.ThrowIfNull(attempt);

        var policy = Resilience.GetExporterPolicy(signal);
        // Both bounds, exactly as Python does it (resilience.py:186):
        // min(max(1, retries + 1), MAX_EXPORT_ATTEMPTS). The lower bound keeps a
        // negative Retries from producing zero attempts; the upper is the ceiling.
        var maxAttempts = Math.Min(Math.Max(1, policy.Retries + 1), Resilience.MaxExportAttempts);

        // Gate the whole export on breaker state before any attempt runs — once
        // per call, not per attempt, and never behind a retries check, so an open
        // breaker is honored at the shipped Retries = 0 default. The
        // TimeoutSeconds > 0 guard is Python's (resilience.py:190): with no
        // timeout there is no pool to saturate and nothing for the breaker to
        // shed. The rejection is recorded in health on both fail_open branches,
        // or an open breaker would be invisible to Health.
        if (policy.TimeoutSeconds > 0 && !Resilience.AllowAttempt(signal))
        {
            Health.RecordExportFailure(signal);
            return policy.FailOpen
                ? ExportAttemptResult.Success(0)
                : ExportAttemptResult.Failed(0);
        }

        for (var index = 0; index < maxAttempts; index++)
        {
            // The deadline gates RETRIES only. The first attempt always runs,
            // even against an already-expired deadline, because otherwise
            // whichever drain runs last against a shared, already-spent
            // Shutdown() deadline would emit nothing at all.
            if (index > 0)
            {
                if (deadline - DateTimeOffset.UtcNow <= TimeSpan.Zero)
                {
                    return ExportAttemptResult.TimedOut(index);
                }
                Health.IncrementRetries(signal);
                await DelayBoundedByDeadline(policy, index, deadline, cancellationToken).ConfigureAwait(false);
            }

            var (succeeded, timedOut) = await RunAttempt(
                signal, attempt, deadline, cancellationToken).ConfigureAwait(false);

            if (succeeded)
            {
                Resilience.RecordSuccess(signal);
                return ExportAttemptResult.Success(index + 1);
            }
            // Recorded on every failed attempt rather than only after the last
            // retry, so the breaker advances toward tripping even at Retries = 0.
            Resilience.RecordFailure(signal, timedOut);
            Health.RecordExportFailure(signal);
        }

        return ExportAttemptResult.Failed(maxAttempts);
    }

    /// <summary>Run one attempt, converting every fault into a failed attempt.</summary>
    private static async ValueTask<(bool Succeeded, bool TimedOut)> RunAttempt(
        string signal,
        Func<CancellationToken, ValueTask<bool>> attempt,
        DateTimeOffset deadline,
        CancellationToken cancellationToken)
    {
        var budget = deadline - DateTimeOffset.UtcNow;
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        if (budget > TimeSpan.Zero) linked.CancelAfter(budget);

        var started = Stopwatch.GetTimestamp();
        try
        {
            return (await attempt(linked.Token).ConfigureAwait(false), false);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            // The linked source fired at the deadline: a timed-out attempt, not
            // an escaping fault.
            return (false, true);
        }
        catch (OperationCanceledException)
        {
            // The caller's own token: they asked to stop, so stopping is the
            // correct answer rather than a retry or a reported export failure.
            throw;
        }
        catch (TimeoutException)
        {
            return (false, true);
        }
        catch (Exception)
        {
            // A transient export fault — an unreachable collector, say — counts
            // as a failed attempt instead of escaping the loop. Shutdown() must
            // return within one deadline against a dead collector, never throw.
            return (false, false);
        }
        finally
        {
            Health.RecordAttempt(signal, Stopwatch.GetElapsedTime(started));
        }
    }

    /// <summary>
    /// Wait out the backoff, never past the deadline.
    /// </summary>
    /// <remarks>
    /// Exponential in the retry index, matching the other runtimes, and clamped
    /// to the time actually left: a 30-second backoff inside a one-second
    /// shutdown budget must not turn into a 30-second shutdown.
    /// </remarks>
    private static Task DelayBoundedByDeadline(
        ExporterPolicy policy, int index, DateTimeOffset deadline, CancellationToken cancellationToken)
    {
        if (policy.BackoffSeconds <= 0) return Task.CompletedTask;
        var backoff = TimeSpan.FromSeconds(policy.BackoffSeconds * Math.Pow(2, index - 1));
        var remaining = deadline - DateTimeOffset.UtcNow;
        var delay = backoff < remaining ? backoff : remaining;
        return delay > TimeSpan.Zero ? Task.Delay(delay, cancellationToken) : Task.CompletedTask;
    }
}
