// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// One rejected signal increments its dropped counter by exactly one, whichever
/// gate rejected it.
/// </summary>
/// <remarks>
/// Sampling used to record the drop itself and then reject through
/// SignalPipeline.Reject, which records it again — so a sampled-out signal
/// counted twice while a consent rejection counted once. Nothing compared the
/// two paths against each other, so the asymmetry was invisible: each gate's
/// own tests asserted "the counter moved", which was true either way.
/// </remarks>
public class AdmissionAccountingTests
{
    [Theory]
    [InlineData("logs")]
    [InlineData("traces")]
    [InlineData("metrics")]
    public void SamplingRejectionCountsOneDrop(string signal)
    {
        Testing.ResetForTests();
        Sampling.SetSamplingPolicy(signal, new SamplingPolicy { DefaultRate = 0.0 });

        var admission = SignalPipeline.Admit(signal, "event.name");

        Assert.False(admission.Admitted);
        Assert.Equal(1, DroppedFor(signal));
    }

    [Theory]
    [InlineData("logs")]
    [InlineData("traces")]
    [InlineData("metrics")]
    public void ConsentRejectionCountsOneDrop(string signal)
    {
        Testing.ResetForTests();
        Consent.SetConsentLevel(ConsentLevel.None);

        var admission = SignalPipeline.Admit(signal, "event.name");

        Assert.False(admission.Admitted);
        Assert.Equal(1, DroppedFor(signal));
    }

    [Fact]
    public void EveryRejectionPathAgreesOnTheIncrement()
    {
        // The property that matters is not the absolute count but that the
        // gates agree: a caller reading *_dropped cannot tell which gate fired,
        // so an inflated count from one of them silently misreports the rest.
        Testing.ResetForTests();
        Consent.SetConsentLevel(ConsentLevel.None);
        SignalPipeline.Admit("logs", "e");
        var consent = DroppedFor("logs");

        Testing.ResetForTests();
        Sampling.SetSamplingPolicy("logs", new SamplingPolicy { DefaultRate = 0.0 });
        SignalPipeline.Admit("logs", "e");
        var sampling = DroppedFor("logs");

        Assert.Equal(consent, sampling);
    }

    [Fact]
    public void AskingTheSamplerDirectlyDoesNotMoveTheCounter()
    {
        // ProvideTelemetry.ShouldSample answers a question; it does not admit a signal.
        Testing.ResetForTests();
        Sampling.SetSamplingPolicy("logs", new SamplingPolicy { DefaultRate = 0.0 });

        Assert.False(ProvideTelemetry.ShouldSample("logs", "event.name"));
        Assert.Equal(0, DroppedFor("logs"));
    }

    private static long DroppedFor(string signal)
    {
        var snapshot = Health.GetHealthSnapshot();
        return signal switch
        {
            "traces" => snapshot.TracesDropped,
            "metrics" => snapshot.MetricsDropped,
            _ => snapshot.LogsDropped,
        };
    }
}
