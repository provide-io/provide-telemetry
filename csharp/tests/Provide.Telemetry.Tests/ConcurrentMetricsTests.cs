// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

[Collection("Telemetry")]
public class ConcurrentMetricsTests
{
    private const int Iterations = 10_000;

    public ConcurrentMetricsTests() => Testing.ResetForTests();

    [Fact]
    public void ConcurrentHistogramRecordsHaveExactCountAndSum()
    {
        // `_sum += value` is a read-modify-write on an unsynchronized double, so
        // concurrent records silently lost each other — a metric that undercounts
        // under exactly the load worth measuring.
        var histogram = ProvideTelemetry.Histogram("parallel.histogram");
        Parallel.For(0, Iterations, _ => histogram.Record(1));

        Assert.Equal(Iterations, histogram.Count);
        Assert.Equal(Iterations, histogram.Sum);
    }

    [Fact]
    public void ConcurrentGaugeSetsLandOnOneOfTheWrittenValues()
    {
        var gauge = ProvideTelemetry.Gauge("parallel.gauge");
        Parallel.For(0, Iterations, i => gauge.Set(i));

        // A torn double could read back a value nobody ever wrote.
        Assert.InRange(gauge.Value, 0, Iterations - 1);
        Assert.Equal(Math.Floor(gauge.Value), gauge.Value);
    }

    [Fact]
    public void ConcurrentCounterAddsAreExact()
    {
        var counter = ProvideTelemetry.Counter("parallel.counter");
        Parallel.For(0, Iterations, _ => counter.Add(1));
        Assert.Equal(Iterations, counter.Value);
    }

    [Fact]
    public void EveryConcurrentRecordIsCountedInHealth()
    {
        var histogram = ProvideTelemetry.Histogram("parallel.health");
        Parallel.For(0, Iterations, _ => histogram.Record(2.5));

        Assert.Equal(Iterations, ProvideTelemetry.GetHealthSnapshot().MetricsEmitted);
        Assert.Equal(Iterations * 2.5, histogram.Sum);
    }

    [Fact]
    public void ConcurrentEmitsUnderABoundedQueueNeverLeakCapacity()
    {
        // Instrument first: the first facade call lazily starts the runtime and
        // republishes the queue policy from config.
        var counter = ProvideTelemetry.Counter("parallel.bounded");
        ProvideTelemetry.SetQueuePolicy(new QueuePolicy { MetricsMaxSize = 4 });
        Parallel.For(0, Iterations, _ => counter.Add(1));

        // Every admitted emit released its ticket, so the queue is empty again
        // and all four slots are available.
        var tickets = Enumerable.Range(0, 4).Select(_ => Backpressure.TryAcquire("metrics")).ToList();
        Assert.All(tickets, Assert.NotNull);
        Assert.Null(Backpressure.TryAcquire("metrics"));
        foreach (var ticket in tickets) Backpressure.Release(ticket);
    }

    [Fact]
    public void AtomicDoubleAccumulatesExactlyUnderContention()
    {
        var value = new AtomicDouble();
        Parallel.For(0, Iterations, _ => value.Add(0.5));
        Assert.Equal(Iterations * 0.5, value.Read());
    }
}
