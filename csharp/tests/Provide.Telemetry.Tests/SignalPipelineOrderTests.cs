// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Pins the pipeline against <c>spec/pipeline_fixtures.yaml</c>: one order, and
/// exactly one ticket release on every exit path including rejections.
/// </summary>
[Collection("Telemetry")]
public class SignalPipelineOrderTests
{
    public SignalPipelineOrderTests() => Testing.ResetForTests();

    private sealed class RecordingPipelineObserver : ISignalPipelineObserver
    {
        public List<string> Events { get; } = new();

        public void OnStage(string stage) => Events.Add(stage);

        public int ReleaseCount => Events.Count(e => e == PipelineStages.Release);
    }

    private static LogDispatch Dispatch(Action<CanonicalLogRecord>? backend = null) => new()
    {
        SamplingKey = "pipeline.event",
        LogLevel = "INFO",
        Harden = () => new Dictionary<string, object?> { ["password"] = "hunter2" },
        Sanitize = hardened => Pii.SanitizeHardened(hardened, enabled: true),
        Build = payload => CanonicalLogRecord.Create(
            DateTimeOffset.UtcNow, "INFO", "pipeline.event", "pipeline",
            TelemetryConfig.Default(), "", "", payload),
        EmitLocal = _ => { },
        Backend = backend,
    };

    [Fact]
    public void PipelineUsesCanonicalOrderAndReleasesTicketOnce()
    {
        var observer = new RecordingPipelineObserver();
        Assert.True(SignalPipeline.Process(Dispatch(backend: _ => { }), observer));

        Assert.Equal(
            new[]
            {
                "consent", "sampling", "backpressure", "hardening", "pii",
                "receipt", "local", "backend", "health", "release",
            },
            observer.Events);
        Assert.Equal(1, observer.ReleaseCount);
    }

    [Fact]
    public void LocalOnlySuccessSkipsTheBackendStage()
    {
        var observer = new RecordingPipelineObserver();
        Assert.True(SignalPipeline.Process(Dispatch(), observer));

        Assert.Equal(
            new[] { "consent", "sampling", "backpressure", "hardening", "pii", "receipt", "local", "health", "release" },
            observer.Events);
        Assert.Equal(1, observer.ReleaseCount);
    }

    [Fact]
    public void ConsentRejectionStillRecordsHealthAndReleases()
    {
        ProvideTelemetry.SetConsentLevel(ConsentLevel.None);
        var observer = new RecordingPipelineObserver();

        Assert.False(SignalPipeline.Process(Dispatch(), observer));

        Assert.Equal(new[] { "consent", "health", "release" }, observer.Events);
        Assert.Equal(1, observer.ReleaseCount);
        Assert.Equal(1, ProvideTelemetry.GetHealthSnapshot().LogsDropped);
    }

    [Fact]
    public void SamplingRejectionDoesNoPayloadWork()
    {
        ProvideTelemetry.SetSamplingPolicy("logs", new SamplingPolicy { DefaultRate = 0.0 });
        var observer = new RecordingPipelineObserver();

        Assert.False(SignalPipeline.Process(Dispatch(), observer));

        Assert.Equal(new[] { "consent", "sampling", "health", "release" }, observer.Events);
        Assert.Equal(1, observer.ReleaseCount);
    }

    [Fact]
    public void QueueRejectionSkipsHardeningAndExport()
    {
        ProvideTelemetry.SetQueuePolicy(new QueuePolicy { LogsMaxSize = 1 });
        var held = Backpressure.TryAcquire("logs");
        try
        {
            var observer = new RecordingPipelineObserver();
            Assert.False(SignalPipeline.Process(Dispatch(), observer));

            Assert.Equal(new[] { "consent", "sampling", "backpressure", "health", "release" }, observer.Events);
            Assert.Equal(1, observer.ReleaseCount);
            Assert.Equal(1, ProvideTelemetry.GetHealthSnapshot().LogsDropped);
        }
        finally
        {
            Backpressure.Release(held);
        }
    }

    [Fact]
    public void BackendFailureStillRunsHealthAndReleases()
    {
        var observer = new RecordingPipelineObserver();
        var dispatch = Dispatch(backend: _ => throw new InvalidOperationException("exporter down"));

        // The fault reaches the caller — a backend that throws is a bug, not a
        // dropped record — but the ticket comes back regardless.
        Assert.Throws<InvalidOperationException>(() => SignalPipeline.Process(dispatch, observer));

        Assert.Equal(
            new[] { "consent", "sampling", "backpressure", "hardening", "pii", "receipt", "local", "backend", "release" },
            observer.Events);
        Assert.Equal(1, observer.ReleaseCount);
    }

    [Fact]
    public void EveryStageAppearsInTheCanonicalOrderList()
    {
        Assert.Equal(
            new[]
            {
                "consent", "sampling", "backpressure", "hardening", "pii",
                "receipt", "local", "backend", "health", "release",
            },
            PipelineStages.CanonicalOrder);
    }

    [Fact]
    public void ATicketIsReleasedExactlyOncePerAdmittedEvent()
    {
        ProvideTelemetry.SetQueuePolicy(new QueuePolicy { LogsMaxSize = 2 });
        for (var i = 0; i < 50; i++)
        {
            Assert.True(SignalPipeline.Process(Dispatch()));
        }

        var tickets = Enumerable.Range(0, 2).Select(_ => Backpressure.TryAcquire("logs")).ToList();
        Assert.All(tickets, Assert.NotNull);
        Assert.Null(Backpressure.TryAcquire("logs"));
        foreach (var ticket in tickets) Backpressure.Release(ticket);
    }

    [Fact]
    public void HardeningRunsBeforeTheLocalRendererSeesTheRecord()
    {
        CanonicalLogRecord? seen = null;
        SignalPipeline.Process(Dispatch() with { EmitLocal = record => seen = record });

        // The renderer receives the redacted payload, not the caller's value.
        Assert.NotNull(seen);
        Assert.Equal(Pii.Redacted, seen!.Attributes["password"]);
    }
}
