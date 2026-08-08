// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

[Collection("Telemetry")]
public class ScopedContextTests
{
    public ScopedContextTests() => Testing.ResetForTests();

    [Fact]
    public async Task NestedSpanRestoresPredecessorExactlyOnceAcrossAwait()
    {
        using var outer = ProvideTelemetry.GetTracer("scoped").StartSpan("outer");
        var outerId = Context.GetTraceContext().TraceId;
        Assert.Equal(outer.TraceId, outerId);

        await Task.Yield();

        var inner = ProvideTelemetry.GetTracer("scoped").StartSpan("inner");
        Assert.NotEqual(outerId, Context.GetTraceContext().TraceId);

        inner.Dispose();
        // Disposing twice must not unwind a second level: the outer span still
        // owns the ambient context until it ends.
        inner.Dispose();

        Assert.Equal(outerId, Context.GetTraceContext().TraceId);
    }

    [Fact]
    public void EndingASpanRevealsTheParentRatherThanClearingContext()
    {
        // The bug this pins: disposal used to leave the slot empty, so every log
        // line emitted after an inner span closed had no trace id at all.
        ProvideTelemetry.SetTraceContext("0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331");
        using (ProvideTelemetry.GetTracer("scoped").StartSpan("child"))
        {
            Assert.NotEqual("0af7651916cd43dd8448eb211c80319c", Context.GetTraceContext().TraceId);
        }
        Assert.Equal("0af7651916cd43dd8448eb211c80319c", Context.GetTraceContext().TraceId);
    }

    [Fact]
    public void ThreeLevelsUnwindInOrder()
    {
        var tracer = ProvideTelemetry.GetTracer("scoped");
        using var a = tracer.StartSpan("a");
        var idA = Context.GetTraceContext().TraceId;
        var b = tracer.StartSpan("b");
        var idB = Context.GetTraceContext().TraceId;
        var c = tracer.StartSpan("c");

        Assert.NotEqual(idB, Context.GetTraceContext().TraceId);
        c.Dispose();
        Assert.Equal(idB, Context.GetTraceContext().TraceId);
        b.Dispose();
        Assert.Equal(idA, Context.GetTraceContext().TraceId);
    }

    [Fact]
    public void DoubleDisposeReleasesOneTicketOnly()
    {
        // The tracer is resolved first: the first facade call lazily starts the
        // runtime, which republishes the queue policy from config and would
        // otherwise discard the bound this test depends on.
        var tracer = ProvideTelemetry.GetTracer("scoped");
        ProvideTelemetry.SetQueuePolicy(new QueuePolicy { TracesMaxSize = 1 });
        var span = tracer.StartSpan("only");
        span.Dispose();
        span.Dispose();

        // A second release would have raised capacity above the configured
        // bound, letting two concurrent spans through a queue of size one.
        var first = Backpressure.TryAcquire("traces");
        var second = Backpressure.TryAcquire("traces");
        Assert.NotNull(first);
        Assert.Null(second);
        Backpressure.Release(first);
    }

    [Fact]
    public void BoundFieldsRestoreOnScopeDisposal()
    {
        ProvideTelemetry.BindContext(new Dictionary<string, object?> { ["tenant"] = "outer" });
        using (Context.PushContext(new Dictionary<string, object?> { ["tenant"] = "inner" }))
        {
            Assert.Equal("inner", Context.GetBoundFields()["tenant"]);
        }
        Assert.Equal("outer", Context.GetBoundFields()["tenant"]);
    }

    [Fact]
    public async Task ConcurrentTasksDoNotSeeEachOthersSpans()
    {
        var tracer = ProvideTelemetry.GetTracer("scoped");
        var observed = await Task.WhenAll(Enumerable.Range(0, 32).Select(i => Task.Run(() =>
        {
            using var span = tracer.StartSpan($"task-{i}");
            Thread.Yield();
            return (Expected: span.TraceId, Actual: Context.GetTraceContext().TraceId);
        })));

        Assert.All(observed, pair => Assert.Equal(pair.Expected, pair.Actual));
    }
}
