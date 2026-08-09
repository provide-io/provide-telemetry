// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Diagnostics;
using System.Diagnostics.Metrics;

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests;

/// <summary>
/// Drives the OTLP instrument wrappers against real BCL listeners.
/// </summary>
/// <remarks>
/// An <see cref="ActivityListener"/> and a <see cref="MeterListener"/> observe
/// exactly what an exporter would, so these assertions are about what reaches
/// the wire rather than about which of our own methods ran. Nothing here needs
/// a collector, and nothing needs the OTel SDK's own pipeline: the wrappers'
/// contract is that a measurement arrives with the value and tags it was given,
/// and only when admission control allowed it.
/// </remarks>
[Collection("OpenTelemetry")]
public sealed class OtelInstrumentsTests : IDisposable
{
    private readonly ActivitySource _source = new("Provide.Telemetry.Tests.Listened");
    private readonly ActivitySource _unlistened = new("Provide.Telemetry.Tests.Unlistened");
    private readonly ActivityListener _listener;
    private readonly Meter _meter = new("Provide.Telemetry.Tests.Instruments");
    private readonly MeterListener _meterListener = new();
    private readonly List<(string Name, double Value, Dictionary<string, object?> Tags)> _measurements = new();

    public OtelInstrumentsTests()
    {
        Testing.ResetForTests();

        _listener = new ActivityListener
        {
            ShouldListenTo = source => ReferenceEquals(source, _source),
            Sample = (ref ActivityCreationOptions<ActivityContext> _) =>
                ActivitySamplingResult.AllDataAndRecorded,
        };
        ActivitySource.AddActivityListener(_listener);

        _meterListener.InstrumentPublished = (instrument, listener) =>
        {
            if (ReferenceEquals(instrument.Meter, _meter)) listener.EnableMeasurementEvents(instrument);
        };
        _meterListener.SetMeasurementEventCallback<long>(
            (instrument, value, tags, _) => Capture(instrument, value, tags));
        _meterListener.SetMeasurementEventCallback<double>(
            (instrument, value, tags, _) => Capture(instrument, value, tags));
        _meterListener.Start();
    }

    private void Capture(Instrument instrument, double value, ReadOnlySpan<KeyValuePair<string, object?>> tags)
    {
        var copied = new Dictionary<string, object?>(StringComparer.Ordinal);
        foreach (var tag in tags) copied[tag.Key] = tag.Value;
        _measurements.Add((instrument.Name, value, copied));
    }

    public void Dispose()
    {
        _meterListener.Dispose();
        _listener.Dispose();
        _meter.Dispose();
        _source.Dispose();
        _unlistened.Dispose();
        Testing.ResetForTests();
    }

    // ── OtelTracer / OtelSpan ────────────────────────────────────────────────

    [Fact]
    public void StartSpan_PublishesTheActivitysOwnIdentifiersAsAmbientTraceContext()
    {
        var tracer = new OtelTracer(_source, "unit");

        string ambientTrace;
        string ambientSpan;
        string spanTraceId;
        string spanSpanId;
        using (var span = tracer.StartSpan("work"))
        {
            (ambientTrace, ambientSpan) = Context.GetTraceContext();
            (spanTraceId, spanSpanId) = (span.TraceId, span.SpanId);
        }

        // The span reports the SDK's identifiers, not freshly invented ones, and
        // the ambient context carries the same pair so a log line emitted inside
        // the span correlates with it.
        Assert.Matches("^[0-9a-f]{32}$", spanTraceId);
        Assert.Matches("^[0-9a-f]{16}$", spanSpanId);
        Assert.Equal(spanTraceId, ambientTrace);
        Assert.Equal(spanSpanId, ambientSpan);
        Assert.Equal(1, Health.GetHealthSnapshot().TracesEmitted);
    }

    [Fact]
    public void StartSpan_NestedSpansRestoreTheEnclosingContextRatherThanClearingIt()
    {
        var tracer = new OtelTracer(_source, "unit");

        using var outer = tracer.StartSpan("outer");
        var outerSpanId = outer.SpanId;

        using (var inner = tracer.StartSpan("inner"))
        {
            Assert.NotEqual(outerSpanId, inner.SpanId);
            Assert.Equal(inner.SpanId, Context.GetTraceContext().SpanId);
        }

        Assert.Equal(outerSpanId, Context.GetTraceContext().SpanId);
    }

    [Fact]
    public void StartSpan_ConsentNoneDropsTheSpanAndCountsIt()
    {
        ProvideTelemetry.SetConsentLevel(ConsentLevel.None);
        var tracer = new OtelTracer(_source, "unit");

        using var span = tracer.StartSpan("work");

        Assert.Equal("00000000000000000000000000000000", span.TraceId);
        Assert.Equal("0000000000000000", span.SpanId);
        // A refused span must not publish context either, or a log line would
        // claim to belong to a trace that was never recorded.
        Assert.Equal(("", ""), Context.GetTraceContext());
        var health = Health.GetHealthSnapshot();
        Assert.Equal(0, health.TracesEmitted);
        Assert.Equal(1, health.TracesDropped);
    }

    [Fact]
    public void StartSpan_UnsampledBySdkYieldsADroppedSpanAndReturnsTheQueueTicket()
    {
        // No listener is attached to _unlistened, so StartActivity answers null:
        // the SDK's own sampler declined. The wrapper must hand back the queue
        // ticket it took, or a bounded traces queue leaks a slot per decline.
        ProvideTelemetry.SetQueuePolicy(new QueuePolicy { TracesMaxSize = 1 });
        var declining = new OtelTracer(_unlistened, "unit");

        using (var dropped = declining.StartSpan("work"))
        {
            Assert.Equal("00000000000000000000000000000000", dropped.TraceId);
        }

        Assert.Equal(0, Health.GetHealthSnapshot().TracesEmitted);
        using var next = new OtelTracer(_source, "unit").StartSpan("work");
        Assert.NotEqual("00000000000000000000000000000000", next.TraceId);
    }

    [Fact]
    public void StartSpan_ReturnsTheQueueTicketWhenActivityCreationThrows()
    {
        // A listener callback that faults escapes StartActivity. The ticket is
        // released on the way out so a single misbehaving instrumentation
        // library cannot exhaust the bounded traces queue.
        ProvideTelemetry.SetQueuePolicy(new QueuePolicy { TracesMaxSize = 1 });
        using var faulting = new ActivityListener
        {
            ShouldListenTo = source => ReferenceEquals(source, _source),
            Sample = (ref ActivityCreationOptions<ActivityContext> _) =>
                ActivitySamplingResult.AllDataAndRecorded,
            ActivityStarted = _ => throw new InvalidOperationException("listener exploded"),
        };
        ActivitySource.AddActivityListener(faulting);

        var tracer = new OtelTracer(_source, "unit");
        var thrown = Assert.Throws<InvalidOperationException>(() => tracer.StartSpan("work"));
        Assert.Equal("listener exploded", thrown.Message);

        faulting.Dispose();
        using var next = tracer.StartSpan("work");
        Assert.NotEqual("00000000000000000000000000000000", next.TraceId);
    }

    [Fact]
    public void Span_SetAttribute_ReachesTheActivityAsATag()
    {
        Activity? observed = null;
        using var capture = new ActivityListener
        {
            ShouldListenTo = source => ReferenceEquals(source, _source),
            Sample = (ref ActivityCreationOptions<ActivityContext> _) =>
                ActivitySamplingResult.AllDataAndRecorded,
            ActivityStarted = activity => observed = activity,
        };
        ActivitySource.AddActivityListener(capture);

        using (var span = new OtelTracer(_source, "unit").StartSpan("work"))
        {
            span.SetAttribute("http.route", "/orders");
            span.SetAttribute("retry.count", 3);
        }

        Assert.NotNull(observed);
        Assert.Equal("/orders", observed!.GetTagItem("http.route"));
        Assert.Equal(3, observed.GetTagItem("retry.count"));
    }

    [Fact]
    public void Span_RecordException_AddsTheCanonicalExceptionEvent()
    {
        Activity? observed = null;
        using var capture = new ActivityListener
        {
            ShouldListenTo = source => ReferenceEquals(source, _source),
            Sample = (ref ActivityCreationOptions<ActivityContext> _) =>
                ActivitySamplingResult.AllDataAndRecorded,
            ActivityStarted = activity => observed = activity,
        };
        ActivitySource.AddActivityListener(capture);

        using (var span = new OtelTracer(_source, "unit").StartSpan("work"))
        {
            span.RecordException(new InvalidOperationException("kaboom"));
        }

        var evt = Assert.Single(observed!.Events);
        Assert.Equal("exception", evt.Name);
        var tags = evt.Tags.ToDictionary(t => t.Key, t => t.Value, StringComparer.Ordinal);
        Assert.Equal("kaboom", tags["exception.message"]);
        Assert.Equal(typeof(InvalidOperationException).FullName, tags["exception.type"]);
    }

    [Theory]
    // "ok" in any casing is the only spelling that means success; everything
    // else — including the empty string — is an error, so a typo cannot silently
    // mark a failed span healthy. The description rides along only on Error:
    // the OTel spec says a description is meaningless on a successful span, and
    // Activity.SetStatus discards it there.
    [InlineData("ok", ActivityStatusCode.Ok, null)]
    [InlineData("OK", ActivityStatusCode.Ok, null)]
    [InlineData("error", ActivityStatusCode.Error, "because")]
    [InlineData("", ActivityStatusCode.Error, "because")]
    public void Span_SetStatus_MapsOnlyOkToSuccess(
        string status, ActivityStatusCode expected, string? expectedDescription)
    {
        Activity? observed = null;
        using var capture = new ActivityListener
        {
            ShouldListenTo = source => ReferenceEquals(source, _source),
            Sample = (ref ActivityCreationOptions<ActivityContext> _) =>
                ActivitySamplingResult.AllDataAndRecorded,
            ActivityStarted = activity => observed = activity,
        };
        ActivitySource.AddActivityListener(capture);

        using (var span = new OtelTracer(_source, "unit").StartSpan("work"))
        {
            span.SetStatus(status, "because");
        }

        Assert.Equal(expected, observed!.Status);
        Assert.Equal(expectedDescription, observed.StatusDescription);
    }

    [Fact]
    public void Span_DoubleDispose_ReleasesOneTicketAndUnwindsOneContextLevel()
    {
        ProvideTelemetry.SetQueuePolicy(new QueuePolicy { TracesMaxSize = 2 });
        var tracer = new OtelTracer(_source, "unit");

        using var outer = tracer.StartSpan("outer");
        var inner = tracer.StartSpan("inner");
        inner.Dispose();
        inner.Dispose();

        // A second unwind would roll the context past the outer span, and a
        // second release would hand back a slot the queue never lent out.
        Assert.Equal(outer.SpanId, Context.GetTraceContext().SpanId);
        using var third = tracer.StartSpan("third");
        Assert.NotEqual("00000000000000000000000000000000", third.TraceId);
        using var refused = tracer.StartSpan("refused");
        Assert.Equal("00000000000000000000000000000000", refused.TraceId);
    }

    // ── OtelMeter instruments ────────────────────────────────────────────────

    [Fact]
    public void Counter_Add_EmitsTheMeasurementWithItsAttributesAndTracksTheValue()
    {
        var counter = new OtelMeter(_meter).CreateCounter("orders.placed");

        counter.Add(2, new Dictionary<string, object?> { ["region"] = "eu", ["tier"] = 1 });
        counter.Add(3);

        Assert.Equal(5, counter.Value);
        Assert.Equal(2, Health.GetHealthSnapshot().MetricsEmitted);
        Assert.Equal(2, _measurements.Count);
        Assert.Equal(("orders.placed", 2.0), (_measurements[0].Name, _measurements[0].Value));
        Assert.Equal("eu", _measurements[0].Tags["region"]);
        Assert.Equal(1, _measurements[0].Tags["tier"]);
        // Null attributes must produce an empty tag list, not a null one.
        Assert.Empty(_measurements[1].Tags);
        Assert.Equal(3.0, _measurements[1].Value);
    }

    [Fact]
    public void Gauge_Set_EmitsTheMeasurementAndReportsTheLastValue()
    {
        var gauge = new OtelMeter(_meter).CreateGauge("queue.depth");

        gauge.Set(4.5, new Dictionary<string, object?> { ["queue"] = "logs" });
        gauge.Set(1.25);

        Assert.Equal(1.25, gauge.Value);
        Assert.Equal(2, _measurements.Count);
        Assert.Equal("queue.depth", _measurements[0].Name);
        Assert.Equal(4.5, _measurements[0].Value);
        Assert.Equal("logs", _measurements[0].Tags["queue"]);
        Assert.Equal(1.25, _measurements[1].Value);
        Assert.Equal(2, Health.GetHealthSnapshot().MetricsEmitted);
    }

    [Fact]
    public void Histogram_Record_EmitsEachObservationAndAccumulatesCountAndSum()
    {
        var histogram = new OtelMeter(_meter).CreateHistogram("request.duration");

        histogram.Record(10.5, new Dictionary<string, object?> { ["route"] = "/a" });
        histogram.Record(4.5);

        Assert.Equal(2, histogram.Count);
        Assert.Equal(15.0, histogram.Sum);
        Assert.Equal(2, _measurements.Count);
        Assert.Equal("request.duration", _measurements[0].Name);
        Assert.Equal("/a", _measurements[0].Tags["route"]);
        Assert.Equal(4.5, _measurements[1].Value);
        Assert.Equal(2, Health.GetHealthSnapshot().MetricsEmitted);
    }

    [Fact]
    public void Instruments_ConsentNoneEmitsNothingToTheMeterAndCountsTheDrop()
    {
        // An installed exporter is not a licence to bypass consent: the live
        // path runs the same admission ladder as the in-process fallbacks.
        var meter = new OtelMeter(_meter);
        var counter = meter.CreateCounter("orders.placed");
        var gauge = meter.CreateGauge("queue.depth");
        var histogram = meter.CreateHistogram("request.duration");
        ProvideTelemetry.SetConsentLevel(ConsentLevel.None);

        counter.Add(7);
        gauge.Set(7.0);
        histogram.Record(7.0);

        Assert.Empty(_measurements);
        Assert.Equal(0, counter.Value);
        Assert.Equal(0.0, gauge.Value);
        Assert.Equal(0, histogram.Count);
        Assert.Equal(0.0, histogram.Sum);
        var health = Health.GetHealthSnapshot();
        Assert.Equal(0, health.MetricsEmitted);
        Assert.Equal(3, health.MetricsDropped);
    }
}
