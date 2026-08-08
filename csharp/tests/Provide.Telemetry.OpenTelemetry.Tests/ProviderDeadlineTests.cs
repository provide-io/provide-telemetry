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
        var stopwatch = Stopwatch.StartNew();

        ProviderDrains.Run(drains.Drains, DateTimeOffset.UtcNow.AddMilliseconds(100), result);
        stopwatch.Stop();

        Assert.InRange(stopwatch.Elapsed.TotalMilliseconds, 50, 2000);
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
