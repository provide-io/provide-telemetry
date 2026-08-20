// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests;

/// <summary>
/// The facade paths that only exist once a backend has installed a provider,
/// and the emit path's promise never to fault its caller.
/// </summary>
[Collection("OpenTelemetry")]
public class LiveProviderPathTests : IDisposable
{
    public LiveProviderPathTests()
    {
        Testing.ResetForTests();
        OpenTelemetryBackendRegistration.Register();
    }

    public void Dispose() => Testing.ResetForTests();

    /// <summary>A config whose providers install against the discard port.</summary>
    private static TelemetryConfig LiveConfig()
    {
        var config = TelemetryConfig.Default();
        const string endpoint = "http://127.0.0.1:9";
        config.Tracing.OtlpEndpoint = endpoint;
        config.Metrics.OtlpEndpoint = endpoint;
        config.Logging.OtlpEndpoint = endpoint;
        return config;
    }

    [Fact]
    public void TheFacadeTracerComesFromTheBackendOnceOneIsInstalled()
    {
        ProvideTelemetry.SetupTelemetry(LiveConfig());
        Assert.True(ProvideTelemetry.GetRuntimeStatus().Providers.Traces);

        using var named = Tracing.GetTracer("named").StartSpan("work");
        using var unnamed = Tracing.Tracer.StartSpan("work");

        // A backend span carries the SDK's identifiers and publishes them as
        // ambient context, which is what distinguishes it from the no-op span
        // the fallback would have returned.
        Assert.Matches("^[0-9a-f]{32}$", named.TraceId);
        Assert.NotEqual(named.SpanId, unnamed.SpanId);
        Assert.Equal(unnamed.SpanId, Context.GetTraceContext().SpanId);
        Assert.Equal(2, Health.GetHealthSnapshot().TracesEmitted);
    }

    [Fact]
    public void TheFacadeMeterComesFromTheBackendOnceOneIsInstalled()
    {
        ProvideTelemetry.SetupTelemetry(LiveConfig());
        Assert.True(ProvideTelemetry.GetRuntimeStatus().Providers.Metrics);

        var counter = Metrics.GetMeter("named").CreateCounter("live.counter");
        counter.Add(3);

        Assert.Equal(3, counter.Value);
        Assert.Equal(1, Health.GetHealthSnapshot().MetricsEmitted);
    }

    [Fact]
    public void ALogEmittedThroughTheFacadeReachesBothTheLocalRendererAndTheBackend()
    {
        ProvideTelemetry.SetupTelemetry(LiveConfig());
        Assert.True(ProvideTelemetry.GetRuntimeStatus().Providers.Logs);

        var writer = new StringWriter();
        var original = Console.Error;
        Console.SetError(writer);
        try
        {
            ProvideTelemetry.GetLogger("live").Info("live.emit.ok");
        }
        finally
        {
            Console.SetError(original);
        }

        Assert.Contains("live.emit.ok", writer.ToString());
        Assert.Equal(1, Health.GetHealthSnapshot().LogsEmitted);
        // Best-effort delivery to a discard port is not a failure to report.
        Assert.Equal(0, Health.GetHealthSnapshot().LogsExportFailures);
    }

    [Fact]
    public void AMalformedRecordIsCountedAsAnExportFailureRatherThanThrown()
    {
        // ITelemetryBackend.EmitLog is documented "must not throw": the caller is
        // in the middle of its own work and a broken record must degrade
        // telemetry, not fault the application. A null level is the cheapest way
        // to make the bridge itself fail, standing in for any exporter fault --
        // MapLevel rejects it explicitly so this stays the case now that level
        // parsing goes through the shared table.
        using var backend = new OpenTelemetryBackend(LiveConfig());
        var malformed = new CanonicalLogRecord(
            DateTimeOffset.UtcNow,
            Level: null!,
            Event: "broken.record.emit",
            ServiceName: "svc",
            Environment: null,
            TraceId: null,
            SpanId: null,
            ErrorFingerprint: null,
            Attributes: new Dictionary<string, object?>());

        backend.EmitLog(malformed);

        Assert.Equal(1, Health.GetHealthSnapshot().LogsExportFailures);
    }

    [Fact]
    public void FlushDrainsEveryOwnedSignalAndLeavesThemInstalled()
    {
        ProvideTelemetry.SetupTelemetry(LiveConfig());
        ProvideTelemetry.GetLogger("live").Info("live.flush.ok");
        Tracing.GetTracer("live").StartSpan("work").Dispose();

        var result = ProvideTelemetry.FlushTelemetry(TimeSpan.FromSeconds(5));

        // Owned and drained, so neither "not installed" nor "not owned".
        foreach (var signal in new[] { result.Logs, result.Traces, result.Metrics })
        {
            Assert.False(signal.NotInstalled);
            Assert.False(signal.NotOwned);
        }
        Assert.True(ProvideTelemetry.GetRuntimeStatus().Providers.Traces);
    }
}

/// <summary>Deadline handling inside a single export attempt.</summary>
[Collection("OpenTelemetry")]
public class ExportAttemptDeadlineTests
{
    public ExportAttemptDeadlineTests() => Testing.ResetForTests();

    [Fact]
    public async Task AnAttemptCancelledByItsOwnDeadlineCountsAsATimeout()
    {
        // The linked token fires at the deadline. That cancellation is this
        // executor's own doing, so it is a timed-out attempt — which advances
        // the breaker — rather than a fault escaping to the caller.
        Resilience.SetExporterPolicy(Signals.Logs, new ExporterPolicy
        {
            Retries = 0,
            TimeoutSeconds = 10.0,
        });
        var deadline = DateTimeOffset.UtcNow.AddMilliseconds(50);

        var result = await ResilienceExecutor.ExecuteAsync(
            Signals.Logs,
            async token =>
            {
                await Task.Delay(TimeSpan.FromSeconds(30), token).ConfigureAwait(false);
                return true;
            },
            deadline);

        Assert.Equal(ExportOutcome.Failed, result.Outcome);
        Assert.Equal(1, result.Attempts);
        Assert.Equal(1, Health.GetHealthSnapshot().LogsExportFailures);
    }

    [Fact]
    public async Task ThreeDeadlineCancellationsInARowTripTheBreaker()
    {
        Resilience.SetExporterPolicy(Signals.Logs, new ExporterPolicy
        {
            Retries = 0,
            TimeoutSeconds = 10.0,
        });

        for (var i = 0; i < 3; i++)
        {
            await ResilienceExecutor.ExecuteAsync(
                Signals.Logs,
                async token =>
                {
                    await Task.Delay(TimeSpan.FromSeconds(30), token).ConfigureAwait(false);
                    return true;
                },
                DateTimeOffset.UtcNow.AddMilliseconds(50));
        }

        Assert.Equal("open", Resilience.GetCircuitState(Signals.Logs));
    }

    [Fact]
    public async Task ABackoffShorterThanTheRemainingBudgetIsWaitedOutInFull()
    {
        // The other side of the clamp: when the deadline is generous the delay
        // is the configured backoff, not the whole remaining budget — a retry
        // must not consume the entire timeout just because it could.
        Resilience.SetExporterPolicy(Signals.Logs, new ExporterPolicy
        {
            Retries = 1,
            BackoffSeconds = 0.05,
            TimeoutSeconds = 10.0,
        });
        var started = DateTimeOffset.UtcNow;

        var result = await ResilienceExecutor.ExecuteAsync(
            Signals.Logs,
            _ => ValueTask.FromResult(false),
            started.AddSeconds(30));

        var elapsed = DateTimeOffset.UtcNow - started;
        Assert.Equal(ExportOutcome.Failed, result.Outcome);
        Assert.Equal(2, result.Attempts);
        Assert.InRange(elapsed, TimeSpan.FromMilliseconds(40), TimeSpan.FromSeconds(5));
        Assert.Equal(1, Health.GetHealthSnapshot().LogsRetries);
    }

    [Fact]
    public async Task ANegativeRetryCountStillRunsOneAttempt()
    {
        // The lower bound of max(1, retries + 1): a policy asking for fewer than
        // zero retries must not turn into an export that never happens.
        Resilience.SetExporterPolicy(Signals.Logs, new ExporterPolicy { Retries = -5 });
        var ran = 0;

        var result = await ResilienceExecutor.ExecuteAsync(
            Signals.Logs,
            _ => { ran++; return ValueTask.FromResult(true); },
            DateTimeOffset.UtcNow.AddSeconds(5));

        Assert.Equal(1, ran);
        Assert.True(result.Succeeded);
        Assert.Equal(1, result.Attempts);
    }

    [Fact]
    public async Task ANullAttemptDelegateIsRejected()
    {
        await Assert.ThrowsAsync<ArgumentNullException>(async () => await ResilienceExecutor.ExecuteAsync(
            Signals.Logs, null!, DateTimeOffset.UtcNow.AddSeconds(1)));
    }
}

