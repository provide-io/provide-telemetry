// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// The small primitives the larger suites lean on: queue accounting, sampler
/// clamping, health bookkeeping, the no-op span, and the exception hierarchy.
/// </summary>
[Collection("Telemetry")]
public class RuntimePrimitiveTests
{
    public RuntimePrimitiveTests() => Testing.ResetForTests();

    // ── backpressure ─────────────────────────────────────────────────────────

    [Fact]
    public void AnUnknownSignalIsUnboundedAndUnticketed()
    {
        // Not an error and not a queue: a name the policy has never heard of has
        // no bound to report and lends no ticket, so nothing to release either.
        Assert.Equal(0, Backpressure.MaxSize("bogus"));
        Assert.Null(Backpressure.TryAcquire("bogus"));
    }

    [Fact]
    public void ABoundedQueueRefusesOnceFullAndRecoversAfterARelease()
    {
        Backpressure.SetQueuePolicy(new QueuePolicy { LogsMaxSize = 2 });

        var first = Backpressure.TryAcquire(Signals.Logs);
        var second = Backpressure.TryAcquire(Signals.Logs);
        var refused = Backpressure.TryAcquire(Signals.Logs);

        Assert.NotNull(first);
        Assert.NotNull(second);
        Assert.Null(refused);

        Backpressure.Release(first);
        Assert.NotNull(Backpressure.TryAcquire(Signals.Logs));
    }

    [Fact]
    public void ReleasingATicketTwiceReturnsOnlyOneSlot()
    {
        Backpressure.SetQueuePolicy(new QueuePolicy { MetricsMaxSize = 1 });
        var ticket = Backpressure.TryAcquire(Signals.Metrics)!;

        Backpressure.Release(ticket);
        Backpressure.Release(ticket);
        Backpressure.Release(null);

        Assert.NotNull(Backpressure.TryAcquire(Signals.Metrics));
        Assert.Null(Backpressure.TryAcquire(Signals.Metrics));
    }

    [Fact]
    public void NegativeQueueSizesClampToUnlimited()
    {
        Backpressure.SetQueuePolicy(new QueuePolicy { TracesMaxSize = -5 });

        Assert.Equal(0, Backpressure.GetQueuePolicy().TracesMaxSize);
        for (var i = 0; i < 50; i++) Assert.NotNull(Backpressure.TryAcquire(Signals.Traces));
    }

    [Fact]
    public void InstallingAPolicyResetsTheOutstandingCounts()
    {
        Backpressure.SetQueuePolicy(new QueuePolicy { LogsMaxSize = 1 });
        Assert.NotNull(Backpressure.TryAcquire(Signals.Logs));
        Assert.Null(Backpressure.TryAcquire(Signals.Logs));

        Backpressure.SetQueuePolicy(new QueuePolicy { LogsMaxSize = 1 });

        Assert.NotNull(Backpressure.TryAcquire(Signals.Logs));
    }

    // ── sampling ─────────────────────────────────────────────────────────────

    [Fact]
    public void ANullSamplingPolicyBecomesTheAlwaysSampleDefault()
    {
        var stored = Sampling.SetSamplingPolicy(Signals.Logs, null!);

        Assert.Equal(1.0, stored.DefaultRate);
        Assert.Null(stored.Overrides);
        Assert.True(Sampling.ShouldSample(Signals.Logs, "any"));
    }

    [Fact]
    public void ANaNRateSamplesNothing()
    {
        // NaN compares false against every bound, so clamping alone would leave
        // it intact and make the sampler's behavior undefined.
        var stored = Sampling.SetSamplingPolicy(Signals.Logs, new SamplingPolicy { DefaultRate = double.NaN });

        Assert.Equal(0.0, stored.DefaultRate);
        Assert.False(Sampling.ShouldSample(Signals.Logs, "any"));
    }

    [Fact]
    public void PerKeyOverridesAreClampedIndependentlyOfTheDefault()
    {
        var stored = Sampling.SetSamplingPolicy(Signals.Traces, new SamplingPolicy
        {
            DefaultRate = 1.0,
            Overrides = new Dictionary<string, double> { ["noisy"] = -3.0, ["loud"] = 7.0 },
        });

        Assert.Equal(0.0, stored.Overrides!["noisy"]);
        Assert.Equal(1.0, stored.Overrides["loud"]);
        Assert.False(Sampling.ShouldSample(Signals.Traces, "noisy"));
        Assert.True(Sampling.ShouldSample(Signals.Traces, "loud"));
        Assert.True(Sampling.ShouldSample(Signals.Traces, "unlisted"));
    }

    [Fact]
    public void AnUnsetSignalDefaultsToAlwaysSample()
    {
        Assert.Equal(1.0, Sampling.GetSamplingPolicy(Signals.Metrics).DefaultRate);
    }

    // ── health ───────────────────────────────────────────────────────────────

    [Fact]
    public void ANullSetupErrorIsStoredAsTheEmptyString()
    {
        Health.SetSetupError(null!);

        Assert.Equal("", Health.GetHealthSnapshot().SetupError);
    }

    [Fact]
    public void SetupErrorRoundTripsAndClearsOnReset()
    {
        Health.SetSetupError("collector unreachable");
        Assert.Equal("collector unreachable", Health.GetHealthSnapshot().SetupError);

        Testing.ResetForTests();

        Assert.Equal("", Health.GetHealthSnapshot().SetupError);
    }

    [Fact]
    public void EveryCounterStartsAtZeroWithClosedBreakers()
    {
        var snapshot = Health.GetHealthSnapshot();

        Assert.Equal(0, snapshot.LogsEmitted + snapshot.TracesEmitted + snapshot.MetricsEmitted);
        Assert.Equal(0, snapshot.LogsDropped + snapshot.TracesDropped + snapshot.MetricsDropped);
        Assert.Equal(0, snapshot.ReceiptFailures);
        Assert.Equal("closed", snapshot.TracesCircuitState);
        Assert.Equal("closed", snapshot.MetricsCircuitState);
    }

    // ── consent edge ─────────────────────────────────────────────────────────

    [Fact]
    public void ANullLogLevelRanksAtTheBottomRatherThanFaulting()
    {
        Consent.SetConsentLevel(ConsentLevel.Minimal);

        Assert.False(Consent.ShouldAllow(Signals.Logs, null!));
    }

    // ── context scopes ───────────────────────────────────────────────────────

    [Fact]
    public void PushTraceContextTreatsNullIdentifiersAsEmptyAndStillRestores()
    {
        Context.SetTraceContext("0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331");

        using (Context.PushTraceContext(null!, null!))
        {
            Assert.Equal(("", ""), Context.GetTraceContext());
        }

        Assert.Equal(("0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331"), Context.GetTraceContext());
    }

    // ── the no-op span ───────────────────────────────────────────────────────

    [Fact]
    public void ANoOpSpanAcceptsEveryMutatorWithoutChangingItsIdentity()
    {
        using var span = new NoOpTracer().StartSpan("work");
        var (traceId, spanId) = (span.TraceId, span.SpanId);

        span.SetAttribute("k", "v");
        span.RecordException(new InvalidOperationException("boom"));
        span.SetStatus("error", "because");

        // The fallback span records nothing by design; what it must not do is
        // fault, or forget who it is.
        Assert.Equal(traceId, span.TraceId);
        Assert.Equal(spanId, span.SpanId);
    }

    [Fact]
    public void TraceOfAFunctionReturnsTheValueAndPublishesContextWhileItRuns()
    {
        var observed = Tracing.Trace("work", () => Context.GetTraceContext());

        Assert.Equal(32, observed.TraceId.Length);
        Assert.Equal(16, observed.SpanId.Length);
        // The span is disposed on the way out, so the context is unwound.
        Assert.Equal(("", ""), Context.GetTraceContext());
    }

    [Fact]
    public void TraceRejectsANullDelegate()
    {
        Assert.Throws<ArgumentNullException>(() => Tracing.Trace("work", (Action)null!));
        Assert.Throws<ArgumentNullException>(() => Tracing.Trace("work", (Func<int>)null!));
    }

    // ── the exception hierarchy ──────────────────────────────────────────────

    [Fact]
    public void TelemetryErrorsCarryTheirInnerCause()
    {
        var cause = new InvalidOperationException("root cause");

        var telemetry = new TelemetryError("wrapper", cause);
        var configuration = new ConfigurationError("config wrapper", cause);

        Assert.Same(cause, telemetry.InnerException);
        Assert.Same(cause, configuration.InnerException);
        Assert.Equal("config wrapper", configuration.Message);
        // Every telemetry error is catchable as the base type.
        Assert.IsAssignableFrom<TelemetryError>(configuration);
        Assert.IsAssignableFrom<TelemetryError>(new EventSchemaError("schema"));
        Assert.IsAssignableFrom<TelemetryError>(new ProviderImmutableError("frozen"));
    }

    // ── the backend registry ─────────────────────────────────────────────────

    [Fact]
    public void RegisteringANullFactoryIsRejected()
    {
        Assert.Throws<ArgumentNullException>(() => TelemetryBackendRegistry.Register(null!));
    }

    [Fact]
    public void TheSuiteRunsWithAFactoryInstalled()
    {
        // The module initializer registers the OTLP factory once for the whole
        // assembly; this is the assertion that the opt-in actually happened.
        Assert.True(TelemetryBackendRegistry.IsRegistered);
    }

    [Fact]
    public void HostProviderMarksAreIndependentAndClearable()
    {
        TelemetryBackendRegistry.MarkHostProviders(traces: true);
        Assert.Equal(new ProviderFlags(false, true, false), TelemetryBackendRegistry.HostProviders);

        TelemetryBackendRegistry.MarkHostProviders(metrics: true, logs: true);
        // Each call replaces the whole set rather than accumulating.
        Assert.Equal(new ProviderFlags(true, false, true), TelemetryBackendRegistry.HostProviders);
        Assert.True(TelemetryBackendRegistry.HostProviders.Any);

        TelemetryBackendRegistry.ClearHostProviders();
        Assert.Equal(ProviderFlags.None, TelemetryBackendRegistry.HostProviders);
        Assert.False(TelemetryBackendRegistry.HostProviders.Any);
    }

    // ── lifecycle generation ─────────────────────────────────────────────────

    [Fact]
    public void AGenerationWithNoBackendOwnsNoProviders()
    {
        var generation = new LifecycleGeneration(7, TelemetryConfig.Default(), null, RuntimeState.Ready);

        Assert.Equal(7, generation.Number);
        Assert.Equal(ProviderFlags.None, generation.Providers);
        Assert.Equal(RuntimeState.Ready, generation.State);
    }

    // ── receipts ─────────────────────────────────────────────────────────────

    [Fact]
    public void TestModeIsOnForTheSuiteSoReceiptsNeedNoSink()
    {
        // Outside test mode, enabling receipts without a sink is refused; the
        // built-in collector is what makes the no-sink call legal here.
        Assert.True(Receipts.IsTestMode);
        Receipts.EnableReceipts(true, "", "svc");
        Assert.Empty(Receipts.GetEmittedReceiptsForTests());
    }

    // ── fingerprints ─────────────────────────────────────────────────────────

    [Fact]
    public void AnUnqualifiedFrameFunctionIsUsedWhole()
    {
        // A frame whose method name carries no namespace has no dotted leaf to
        // take, so the whole name is the function.
        Assert.Equal(
            new[] { "file:main" },
            Fingerprint.ExtractFrames("   at main() in /src/File.cs:line 1"));
    }

    [Fact]
    public void AFileWithNoExtensionKeepsItsWholeLeafName()
    {
        Assert.Equal(
            new[] { "makefile:run" },
            Fingerprint.ExtractFrames("   at Ns.T.Run() in /src/Makefile:line 1"));
    }
}
