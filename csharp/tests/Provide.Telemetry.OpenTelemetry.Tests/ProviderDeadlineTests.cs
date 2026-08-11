// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Diagnostics;

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests;

/// <summary>
/// A flush or shutdown must cost the caller one deadline, not one per installed
/// signal.
/// </summary>
[Collection("OpenTelemetry")]
public class ProviderDeadlineTests
{
    public ProviderDeadlineTests() => Testing.ResetForTests();

    /// <summary>Three drains that each block for longer than any sane budget.</summary>
    private sealed class BlockingDrains
    {
        private readonly TimeSpan _blockFor;
        private int _concurrent;

        public BlockingDrains(TimeSpan blockFor) => _blockFor = blockFor;

        public int MaximumConcurrent { get; private set; }

        public IReadOnlyList<ProviderDrain> Drains => new[]
        {
            new ProviderDrain(Signals.Logs, Block),
            new ProviderDrain(Signals.Traces, Block),
            new ProviderDrain(Signals.Metrics, Block),
        };

        private bool Block(int budgetMs)
        {
            var running = Interlocked.Increment(ref _concurrent);
            lock (this)
            {
                if (running > MaximumConcurrent) MaximumConcurrent = running;
            }
            try
            {
                Thread.Sleep(_blockFor);
                return true;
            }
            finally
            {
                Interlocked.Decrement(ref _concurrent);
            }
        }
    }

    [Fact]
    public void ShutdownUsesOneDeadlineAndDrainsSignalsTogether()
    {
        // Sequential drains would cost 3 x the budget against a collector that
        // never answers. Overlapping them keeps the whole operation inside one.
        var drains = new BlockingDrains(TimeSpan.FromSeconds(5));
        var result = new FlushResult();

        // Each drain parks a pool thread for the whole budget, so all three must
        // already be running for the overlap to be observable. The pool starts
        // with ProcessorCount workers and injects further ones on a timer
        // measured in hundreds of milliseconds; on a 2-core CI runner the third
        // drain had not been dispatched before the budget expired, and the test
        // failed with "observed 1 concurrent drains" while the code under test
        // was correct. Raising the floor removes the ramp-up without touching
        // what is being asserted.
        ThreadPool.GetMinThreads(out var workers, out var completionPorts);
        ThreadPool.SetMinThreads(Math.Max(workers, 8), completionPorts);
        var stopwatch = Stopwatch.StartNew();
        try
        {
            // 500ms rather than 100ms for the same reason: the assertion is that
            // three 5s drains cost one budget instead of 15s, and a budget an
            // order of magnitude above the scheduler's jitter tests that just as
            // sharply while leaving no room for a slow dispatch to decide it.
            ProviderDrains.Run(drains.Drains, DateTimeOffset.UtcNow.AddMilliseconds(500), result);
            stopwatch.Stop();
        }
        finally
        {
            ThreadPool.SetMinThreads(workers, completionPorts);
        }

        Assert.InRange(stopwatch.Elapsed.TotalMilliseconds, 50, 3000);
        Assert.True(drains.MaximumConcurrent >= 3, $"observed {drains.MaximumConcurrent} concurrent drains");
    }

    [Fact]
    public void AbandonedDrainsAreReportedAsTimedOut()
    {
        var drains = new BlockingDrains(TimeSpan.FromSeconds(5));
        var result = new FlushResult();

        ProviderDrains.Run(drains.Drains, DateTimeOffset.UtcNow.AddMilliseconds(50), result);

        Assert.True(result.Logs.TimedOut);
        Assert.True(result.Traces.TimedOut);
        Assert.True(result.Metrics.TimedOut);
        Assert.False(result.Logs.Flushed);
    }

    [Fact]
    public void CompletedDrainsAreReportedAsFlushed()
    {
        var result = new FlushResult();
        var drains = new[]
        {
            new ProviderDrain(Signals.Logs, _ => true),
            new ProviderDrain(Signals.Traces, _ => false),
        };

        ProviderDrains.Run(drains, DateTimeOffset.UtcNow.AddSeconds(5), result);

        Assert.True(result.Logs.Flushed);
        Assert.False(result.Traces.Flushed);
        Assert.True(result.Traces.Failed);
        // Nothing was offered for metrics at all.
        Assert.False(result.Metrics.Flushed);
    }

    [Fact]
    public void NoDrainsLeavesTheResultUntouched()
    {
        var result = FlushResults.Undrained(ProviderFlags.None, ProviderFlags.None);
        ProviderDrains.Run(Array.Empty<ProviderDrain>(), DateTimeOffset.UtcNow, result);
        Assert.True(result.Logs.NotInstalled);
        Assert.False(result.Logs.TimedOut);
    }

    /// <summary>
    /// The drain blocks its caller, so a caller that must not be blocked is
    /// counted — the .NET reading of async_blocking_risk_*.
    /// </summary>
    [Fact]
    public void DrainingFromASynchronizationContextCountsAsAsyncBlockingRisk()
    {
        var original = SynchronizationContext.Current;
        try
        {
            SynchronizationContext.SetSynchronizationContext(new SynchronizationContext());
            var drains = new[]
            {
                new ProviderDrain(Signals.Logs, _ => true),
                new ProviderDrain(Signals.Traces, _ => true),
            };

            ProviderDrains.Run(drains, DateTimeOffset.UtcNow.AddSeconds(5), new FlushResult());
        }
        finally
        {
            SynchronizationContext.SetSynchronizationContext(original);
        }

        var health = ProvideTelemetry.GetHealthSnapshot();
        Assert.Equal(1, health.LogsAsyncBlockingRisk);
        Assert.Equal(1, health.TracesAsyncBlockingRisk);
        // Metrics was never drained, so nothing blocked on its behalf.
        Assert.Equal(0, health.MetricsAsyncBlockingRisk);
    }

    /// <summary>
    /// No context means no thread that blocking would starve — a console host or
    /// an ASP.NET Core request, which is the ordinary case.
    /// </summary>
    [Fact]
    public void DrainingWithoutASynchronizationContextCountsNoRisk()
    {
        var original = SynchronizationContext.Current;
        try
        {
            SynchronizationContext.SetSynchronizationContext(null);
            ProviderDrains.Run(
                new[] { new ProviderDrain(Signals.Logs, _ => true) },
                DateTimeOffset.UtcNow.AddSeconds(5),
                new FlushResult());
        }
        finally
        {
            SynchronizationContext.SetSynchronizationContext(original);
        }

        Assert.Equal(0, ProvideTelemetry.GetHealthSnapshot().LogsAsyncBlockingRisk);
    }

    [Fact]
    public void ShutdownReturnsWithinOneDeadlineAgainstADeadCollector()
    {
        OpenTelemetryBackendRegistration.Register();
        var config = TelemetryConfig.Default();
        // A reserved-discard address: connections hang rather than being refused.
        config.Tracing.OtlpEndpoint = "http://192.0.2.1:4318";
        config.Metrics.OtlpEndpoint = "http://192.0.2.1:4318";
        config.Logging.OtlpEndpoint = "http://192.0.2.1:4318";

        ProvideTelemetry.SetupTelemetry(config);
        ProvideTelemetry.GetLogger("deadline").Info("deadline.probe");

        var stopwatch = Stopwatch.StartNew();
        ProvideTelemetry.ShutdownTelemetry();
        stopwatch.Stop();

        Assert.True(stopwatch.Elapsed < TimeSpan.FromSeconds(30), $"shutdown took {stopwatch.Elapsed}");
    }

    [Fact]
    public void ProviderDisposalIsBoundedByTheSameShutdownDeadline()
    {
        // The advertised shutdown budget must cover the whole path, including
        // provider disposal: TracerProvider.Dispose drains its batch processor
        // against the exporter, and against a black-hole collector that drain
        // used to run on OTel's own default timeout, long after the deadline
        // the caller was promised had passed.
        var config = TelemetryConfig.Default();
        config.ServiceName = "deadline-suite";
        // A reserved-discard address: connections hang rather than being refused.
        config.Tracing.OtlpEndpoint = "http://192.0.2.1:4318";
        config.Metrics.OtlpEndpoint = "http://192.0.2.1:4318";
        config.Logging.OtlpEndpoint = "http://192.0.2.1:4318";
        var backend = new OpenTelemetryBackend(config);
        backend.EmitLog(new CanonicalLogRecord(
            DateTimeOffset.UtcNow,
            Level: "INFO",
            Event: "deadline.disposal.probe",
            ServiceName: "deadline-suite",
            Environment: null,
            TraceId: null,
            SpanId: null,
            ErrorFingerprint: null,
            Attributes: new Dictionary<string, object?>()));

        var stopwatch = Stopwatch.StartNew();
        backend.Shutdown(DateTimeOffset.UtcNow + TimeSpan.FromMilliseconds(500));
        backend.Dispose();
        stopwatch.Stop();

        // Generous headroom over the 500ms budget for scheduler jitter — the
        // regression this pins was multi-second (OTel's per-processor default
        // shutdown timeouts stacking after the deadline had already expired).
        Assert.True(stopwatch.Elapsed < TimeSpan.FromSeconds(5), $"bounded shutdown took {stopwatch.Elapsed}");
    }

    [Fact]
    public void FlushPreservesInstalledProvidersAndShutdownDetachesThem()
    {
        OpenTelemetryBackendRegistration.Register();
        var config = TelemetryConfig.Default();
        config.Tracing.OtlpEndpoint = "http://127.0.0.1:4318";
        ProvideTelemetry.SetupTelemetry(config);

        ProvideTelemetry.FlushTelemetry(TimeSpan.FromMilliseconds(100));
        Assert.True(ProvideTelemetry.GetRuntimeStatus().Providers.Traces);

        ProvideTelemetry.ShutdownTelemetry();
        Assert.False(ProvideTelemetry.GetRuntimeStatus().Providers.Traces);
    }

    [Fact]
    public void HostAdoptedProvidersReportNotOwnedRatherThanNotInstalled()
    {
        TelemetryBackendRegistry.MarkHostProviders(logs: true);
        ProvideTelemetry.SetupTelemetry();

        var result = ProvideTelemetry.FlushTelemetry(TimeSpan.FromMilliseconds(50));

        // A host's batch processor is not ours to drain, and saying "flushed"
        // would tell a caller their records had left when they had not.
        Assert.True(result.Logs.NotOwned);
        Assert.False(result.Logs.NotInstalled);
        Assert.False(result.Logs.Flushed);
        Assert.True(result.Traces.NotInstalled);
    }

    [Fact]
    public void ZeroBudgetFlushReturnsPromptly()
    {
        OpenTelemetryBackendRegistration.Register();
        var config = TelemetryConfig.Default();
        config.Logging.OtlpEndpoint = "http://192.0.2.1:4318";
        ProvideTelemetry.SetupTelemetry(config);

        var stopwatch = Stopwatch.StartNew();
        ProvideTelemetry.FlushTelemetry(TimeSpan.Zero);
        ProvideTelemetry.FlushTelemetry(TimeSpan.FromSeconds(-1));
        stopwatch.Stop();

        Assert.True(stopwatch.Elapsed < TimeSpan.FromSeconds(10), $"zero-budget flush took {stopwatch.Elapsed}");
    }
}
