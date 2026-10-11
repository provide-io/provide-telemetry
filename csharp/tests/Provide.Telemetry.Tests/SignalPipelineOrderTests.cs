// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;
using YamlDotNet.RepresentationModel;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Pins the pipeline against <c>spec/pipeline_fixtures.yaml</c>: one order, and
/// exactly one ticket release on every exit path including rejections.
/// </summary>
/// <remarks>
/// Each case is read from the fixture and compared whole, so the fixture the
/// Go, Rust and TypeScript suites are held to is the one this suite is held to.
/// </remarks>
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

    private static readonly IReadOnlyDictionary<string, string[]> FixtureCases = PipelineFixture.Cases();

    public static TheoryData<string> CaseIds()
    {
        var data = new TheoryData<string>();
        foreach (var id in FixtureCases.Keys) data.Add(id);
        return data;
    }

    /// <summary>Run one fixture case and return the stages observed.</summary>
    private static List<string> Run(string id)
    {
        var observer = new RecordingPipelineObserver();
        switch (id)
        {
            case "consent_rejection":
                ProvideTelemetry.SetConsentLevel(ConsentLevel.None);
                Assert.False(SignalPipeline.Process(Dispatch(), observer));
                break;
            case "sampling_rejection":
                ProvideTelemetry.SetSamplingPolicy("logs", new SamplingPolicy { DefaultRate = 0.0 });
                Assert.False(SignalPipeline.Process(Dispatch(), observer));
                break;
            case "queue_rejection":
                ProvideTelemetry.SetQueuePolicy(new QueuePolicy { LogsMaxSize = 1 });
                var held = Backpressure.TryAcquire("logs");
                Assert.False(SignalPipeline.Process(Dispatch(), observer));
                // The refused record must not have freed a slot it never held.
                Assert.Null(Backpressure.TryAcquire("logs"));
                Backpressure.Release(held);
                break;
            case "local_only_success":
                Assert.True(SignalPipeline.Process(Dispatch(), observer));
                break;
            case "backend_success":
                Assert.True(SignalPipeline.Process(Dispatch(backend: _ => { }), observer));
                break;
            case "backend_failure":
                // The fault reaches the caller — a backend that throws is a bug,
                // not a dropped record — but health runs and the ticket comes back.
                var dispatch = Dispatch(backend: _ => throw new InvalidOperationException("exporter down"));
                Assert.Throws<InvalidOperationException>(() => SignalPipeline.Process(dispatch, observer));
                break;
            default:
                Assert.Fail($"fixture case {id} has no run in this suite");
                break;
        }
        Assert.Equal(1, observer.ReleaseCount);
        return observer.Events;
    }

    [Theory]
    [MemberData(nameof(CaseIds))]
    public void EveryFixtureCaseRunsExactlyItsSequence(string id)
    {
        ProvideTelemetry.SetQueuePolicy(new QueuePolicy { LogsMaxSize = 1 });

        Assert.Equal(FixtureCases[id], Run(id));

        // Whatever the path, the one slot is free again afterwards.
        var ticket = Backpressure.TryAcquire("logs");
        Assert.NotNull(ticket);
        Backpressure.Release(ticket);
    }

    [Theory]
    [InlineData("consent_rejection", 0, 1, 0)]
    [InlineData("sampling_rejection", 0, 1, 0)]
    [InlineData("queue_rejection", 0, 1, 0)]
    [InlineData("backend_success", 1, 0, 0)]
    [InlineData("backend_failure", 1, 0, 1)]
    public void HealthCountsEachPathOnce(string id, long emitted, long dropped, long failures)
    {
        Run(id);

        var health = ProvideTelemetry.GetHealthSnapshot();
        Assert.Equal((emitted, dropped, failures), (health.LogsEmitted, health.LogsDropped, health.LogsExportFailures));
    }

    [Fact]
    public void EveryStageAppearsInTheCanonicalOrderList()
    {
        Assert.Equal(PipelineFixture.Events(), PipelineStages.CanonicalOrder);
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

/// <summary>Reads <c>spec/pipeline_fixtures.yaml</c>.</summary>
internal static class PipelineFixture
{
    public static IReadOnlyList<string> Events() =>
        ((YamlSequenceNode)Root()["events"]).Cast<YamlScalarNode>().Select(s => s.Value!).ToList();

    public static IReadOnlyDictionary<string, string[]> Cases() =>
        ((YamlSequenceNode)Root()["cases"]).Cast<YamlMappingNode>().ToDictionary(
            c => ((YamlScalarNode)c["id"]).Value!,
            c => ((YamlSequenceNode)c["expected"]).Cast<YamlScalarNode>().Select(s => s.Value!).ToArray(),
            StringComparer.Ordinal);

    private static YamlMappingNode Root()
    {
        var yaml = new YamlStream();
        using (var reader = new StreamReader(Find()))
        {
            yaml.Load(reader);
        }
        return (YamlMappingNode)yaml.Documents[0].RootNode;
    }

    private static string Find()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, "spec", "pipeline_fixtures.yaml");
            if (File.Exists(candidate)) return candidate;
            directory = directory.Parent;
        }
        throw new FileNotFoundException("spec/pipeline_fixtures.yaml not found from " + AppContext.BaseDirectory);
    }
}
