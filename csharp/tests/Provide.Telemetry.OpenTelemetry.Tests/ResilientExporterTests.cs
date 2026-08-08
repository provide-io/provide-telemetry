// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Net.Http;

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests;

/// <summary>
/// The exporter policy used to be parsed, stored and reported without ever
/// reaching a call that could fail. These tests exercise it through the executor
/// every real export now runs under.
/// </summary>
[Collection("OpenTelemetry")]
public class ResilientExporterTests
{
    public ResilientExporterTests() => Testing.ResetForTests();

    private static DateTimeOffset In(int milliseconds) =>
        DateTimeOffset.UtcNow.AddMilliseconds(milliseconds);

    [Fact]
    public async Task ExporterRetriesAndUpdatesHealth()
    {
        Resilience.SetExporterPolicy("logs", new ExporterPolicy { Retries = 4, BackoffSeconds = 0 });
        var attempts = 0;

        var result = await ResilienceExecutor.ExecuteAsync(
            "logs", _ => ValueTask.FromResult(++attempts == 3), In(1000));

        Assert.True(result.Succeeded);
        Assert.Equal(3, attempts);
        Assert.Equal(3, result.Attempts);
        Assert.Equal(2L, ProvideTelemetry.GetHealthSnapshot().LogsRetries);
        Assert.True(ProvideTelemetry.GetHealthSnapshot().LogsExportLatencyMs >= 0);
    }

    [Fact]
    public async Task AttemptExceptionDoesNotEscapeExecuteAsync()
    {
        var attempts = 0;

        var result = await ResilienceExecutor.ExecuteAsync(
            "logs",
            _ =>
            {
                attempts++;
                throw new HttpRequestException("collector unreachable");
            },
            In(200));

        Assert.False(result.Succeeded);
        Assert.True(attempts >= 1);
        Assert.Equal(1L, ProvideTelemetry.GetHealthSnapshot().LogsExportFailures);
    }

    [Fact]
    public async Task CircuitBreakerIsConsultedWithZeroRetries()
    {
        // The shipped default is Retries = 0. A breaker check written as
        // `retries > 0 && !AllowAttempt()` would short-circuit here and never
        // consult the breaker at all.
        Resilience.SetExporterPolicy("logs", new ExporterPolicy { Retries = 0, TimeoutSeconds = 0.05 });
        for (var i = 0; i < 3; i++)
        {
            await ResilienceExecutor.ExecuteAsync(
                "logs", _ => throw new TimeoutException(), In(200));
        }

        Assert.Equal("open", Resilience.GetCircuitState("logs"));

        var attempted = false;
        await ResilienceExecutor.ExecuteAsync(
            "logs",
            _ =>
            {
                attempted = true;
                return ValueTask.FromResult(true);
            },
            In(200));

        Assert.False(attempted);
    }

    [Fact]
    public async Task AnOpenBreakerIsVisibleInHealthOnBothFailOpenBranches()
    {
        Resilience.SetExporterPolicy("logs", new ExporterPolicy { TimeoutSeconds = 0.05, FailOpen = true });
        for (var i = 0; i < 3; i++)
        {
            await ResilienceExecutor.ExecuteAsync("logs", _ => throw new TimeoutException(), In(200));
        }
        var before = ProvideTelemetry.GetHealthSnapshot().LogsExportFailures;

        var open = await ResilienceExecutor.ExecuteAsync("logs", _ => ValueTask.FromResult(true), In(200));

        // fail_open swallows the rejection for the caller, so health is the only
        // place an open breaker can be seen.
        Assert.True(open.Succeeded);
        Assert.Equal(0, open.Attempts);
        Assert.Equal(before + 1, ProvideTelemetry.GetHealthSnapshot().LogsExportFailures);
        Assert.Equal(1L, ProvideTelemetry.GetHealthSnapshot().LogsCircuitOpenCount);
    }

    [Fact]
    public async Task AnOpenBreakerWithoutFailOpenReportsFailedRatherThanThrowing()
    {
        Resilience.SetExporterPolicy(
            "traces", new ExporterPolicy { TimeoutSeconds = 0.05, FailOpen = false });
        for (var i = 0; i < 3; i++)
        {
            await ResilienceExecutor.ExecuteAsync("traces", _ => throw new TimeoutException(), In(200));
        }

        var rejected = await ResilienceExecutor.ExecuteAsync(
            "traces", _ => ValueTask.FromResult(true), In(200));

        Assert.Equal(ExportOutcome.Failed, rejected.Outcome);
        Assert.Equal(0, rejected.Attempts);
    }

    [Fact]
    public async Task RetriesClampToMaxExportAttemptsCeiling()
    {
        Resilience.SetExporterPolicy("logs", new ExporterPolicy { Retries = 1_000_000, BackoffSeconds = 0 });
        var attempts = 0;

        var result = await ResilienceExecutor.ExecuteAsync(
            "logs",
            _ =>
            {
                attempts++;
                return ValueTask.FromResult(false);
            },
            In(30_000));

        Assert.False(result.Succeeded);
        Assert.Equal(Resilience.MaxExportAttempts, attempts);
    }

    [Fact]
    public void SetExporterPolicyStoresTheClampedRetryCount()
    {
        // Clamped at the setter as well as in the loop: a policy set
        // programmatically bypasses config validation entirely.
        Resilience.SetExporterPolicy("logs", new ExporterPolicy { Retries = 1_000_000 });
        Assert.Equal(Resilience.MaxExportAttempts - 1, Resilience.GetExporterPolicy("logs").Retries);
    }

    [Fact]
    public async Task ExpiredDeadlineStillMakesOneAttempt()
    {
        var attempted = false;

        var result = await ResilienceExecutor.ExecuteAsync(
            "logs",
            _ =>
            {
                attempted = true;
                return ValueTask.FromResult(true);
            },
            DateTimeOffset.UtcNow.AddSeconds(-1));

        Assert.True(attempted);
        Assert.True(result.Succeeded);
    }

    [Fact]
    public async Task AnExpiredDeadlineStopsFurtherRetries()
    {
        Resilience.SetExporterPolicy("logs", new ExporterPolicy { Retries = 5, BackoffSeconds = 0 });
        var attempts = 0;

        var result = await ResilienceExecutor.ExecuteAsync(
            "logs",
            _ =>
            {
                attempts++;
                return ValueTask.FromResult(false);
            },
            DateTimeOffset.UtcNow.AddSeconds(-1));

        Assert.Equal(1, attempts);
        Assert.Equal(ExportOutcome.TimedOut, result.Outcome);
    }

    [Fact]
    public async Task BackoffNeverOutlivesTheDeadline()
    {
        // A 30-second backoff inside a 200ms budget must not become a 30-second
        // shutdown; the delay is clamped to the time actually left.
        Resilience.SetExporterPolicy("logs", new ExporterPolicy { Retries = 3, BackoffSeconds = 30 });
        var started = DateTimeOffset.UtcNow;

        await ResilienceExecutor.ExecuteAsync("logs", _ => ValueTask.FromResult(false), In(200));

        Assert.True(DateTimeOffset.UtcNow - started < TimeSpan.FromSeconds(5));
    }

    [Fact]
    public async Task CallerCancellationStillPropagates()
    {
        using var cancellation = new CancellationTokenSource();
        await cancellation.CancelAsync();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () =>
            await ResilienceExecutor.ExecuteAsync(
                "logs",
                token => throw new OperationCanceledException(token),
                In(1000),
                cancellation.Token));
    }

    [Fact]
    public async Task ASuccessfulAttemptClosesAHalfOpenBreaker()
    {
        Resilience.SetExporterPolicy("metrics", new ExporterPolicy { TimeoutSeconds = 0.05 });
        for (var i = 0; i < 3; i++)
        {
            await ResilienceExecutor.ExecuteAsync("metrics", _ => throw new TimeoutException(), In(200));
        }
        Assert.Equal("open", Resilience.GetCircuitState("metrics"));
        Assert.Equal(1L, Resilience.GetCircuitOpenCount("metrics"));
    }

    [Fact]
    public async Task ANonTimeoutFailureDoesNotTripTheBreaker()
    {
        // Only timeouts count toward tripping: the breaker sheds load from a
        // saturated exporter, and a collector answering 4xx instantly is not
        // saturating anything.
        Resilience.SetExporterPolicy("logs", new ExporterPolicy { TimeoutSeconds = 0.05 });
        for (var i = 0; i < 5; i++)
        {
            await ResilienceExecutor.ExecuteAsync(
                "logs", _ => throw new HttpRequestException("400"), In(200));
        }
        Assert.Equal("closed", Resilience.GetCircuitState("logs"));
    }

    [Fact]
    public async Task ZeroTimeoutSkipsTheBreakerEntirely()
    {
        // Python's guard (resilience.py:190): with no timeout there is no pool to
        // saturate, so there is nothing for the breaker to shed.
        Resilience.SetExporterPolicy("logs", new ExporterPolicy { TimeoutSeconds = 0 });
        for (var i = 0; i < 5; i++)
        {
            await ResilienceExecutor.ExecuteAsync("logs", _ => throw new TimeoutException(), In(200));
        }

        var attempted = false;
        await ResilienceExecutor.ExecuteAsync(
            "logs",
            _ =>
            {
                attempted = true;
                return ValueTask.FromResult(true);
            },
            In(200));

        Assert.True(attempted);
    }

    [Fact]
    public async Task AnUnknownSignalIsRejected()
    {
        await Assert.ThrowsAsync<ConfigurationError>(async () =>
            await ResilienceExecutor.ExecuteAsync("events", _ => ValueTask.FromResult(true), In(200)));
    }
}
