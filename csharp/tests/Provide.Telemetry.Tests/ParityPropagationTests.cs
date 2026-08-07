// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

[Collection("Telemetry")]
public class ParityPropagationTests
{
    public ParityPropagationTests() => Testing.ResetForTests();

    [Fact]
    public void Propagation_ValidTraceparent()
    {
        var headers = new Dictionary<string, string>
        {
            ["traceparent"] = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        };
        var pc = ProvideTelemetry.ExtractW3CContext(headers);
        Assert.Equal("0af7651916cd43dd8448eb211c80319c", pc.TraceID);
        Assert.Equal("b7ad6b7169203331", pc.SpanID);
    }

    [Fact]
    public void Propagation_OversizedTraceparent_Discarded()
    {
        var huge = "00-" + new string('a', 600) + "-b7ad6b7169203331-01";
        var pc = ProvideTelemetry.ExtractW3CContext(new Dictionary<string, string> { ["traceparent"] = huge });
        Assert.Equal("", pc.Traceparent);
        Assert.Equal("", pc.TraceID);
    }

    [Fact]
    public void Propagation_Malformed_Cleared()
    {
        var pc = ProvideTelemetry.ExtractW3CContext(new Dictionary<string, string>
        {
            ["traceparent"] = "not-a-traceparent",
        });
        Assert.Equal("", pc.Traceparent);
        Assert.Equal("", pc.TraceID);
    }

    [Fact]
    public void Propagation_BindSetsTraceContext()
    {
        var pc = ProvideTelemetry.ExtractW3CContext(new Dictionary<string, string>
        {
            ["traceparent"] = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        });
        ProvideTelemetry.BindPropagationContext(pc);
        var (tid, sid) = ProvideTelemetry.GetTraceContext();
        Assert.Equal("0af7651916cd43dd8448eb211c80319c", tid);
        Assert.Equal("b7ad6b7169203331", sid);
    }

    // ── propagation_guards ───────────────────────────────────────────────────
    // spec/behavioral_fixtures.yaml pins six boundary cases. Both sides of each
    // limit matter: a test that only proves oversize is discarded passes just as
    // happily against an implementation that discards everything.

    [Fact]
    public void PropagationGuards_TraceparentAtLimit_Accepted()
    {
        // A canonical 55-char traceparent is well inside the 512-byte cap.
        var pc = ProvideTelemetry.ExtractW3CContext(new Dictionary<string, string>
        {
            ["traceparent"] = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        });
        Assert.NotEqual("", pc.Traceparent);
        Assert.Equal("0af7651916cd43dd8448eb211c80319c", pc.TraceID);
    }

    [Fact]
    public void PropagationGuards_TraceparentOverLimit_Discarded()
    {
        var pc = ProvideTelemetry.ExtractW3CContext(new Dictionary<string, string>
        {
            ["traceparent"] = new string('x', 513),
        });
        Assert.Equal("", pc.Traceparent);
        Assert.Equal("", pc.TraceID);
    }

    [Fact]
    public void PropagationGuards_Tracestate32Pairs_Accepted()
    {
        var state = string.Join(",", Enumerable.Range(0, 32).Select(i => $"k{i}=v{i}"));
        var pc = ProvideTelemetry.ExtractW3CContext(new Dictionary<string, string> { ["tracestate"] = state });
        Assert.Equal(state, pc.Tracestate);
    }

    [Fact]
    public void PropagationGuards_Tracestate33Pairs_Discarded()
    {
        var state = string.Join(",", Enumerable.Range(0, 33).Select(i => $"k{i}=v{i}"));
        var pc = ProvideTelemetry.ExtractW3CContext(new Dictionary<string, string> { ["tracestate"] = state });
        Assert.Equal("", pc.Tracestate);
    }

    [Fact]
    public void PropagationGuards_BaggageAtLimit_Accepted()
    {
        var baggage = "k=" + new string('v', 8192 - 2);
        var pc = ProvideTelemetry.ExtractW3CContext(new Dictionary<string, string> { ["baggage"] = baggage });
        Assert.Equal(baggage, pc.Baggage);
    }

    [Fact]
    public void PropagationGuards_BaggageOverLimit_Discarded()
    {
        var baggage = "k=" + new string('v', 8192 - 1);
        var pc = ProvideTelemetry.ExtractW3CContext(new Dictionary<string, string> { ["baggage"] = baggage });
        Assert.Equal("", pc.Baggage);
    }

    // ── propagation_oversized_traceparent ────────────────────────────────────

    [Fact]
    public void PropagationOversizedTraceparent_TrailingSegment_Rejected()
    {
        // Structural, not length-based: a 5th hyphen-separated segment must be
        // rejected outright — no truncation, no partial acceptance. The oversize
        // *length* case is propagation_guards' job, above.
        var pc = ProvideTelemetry.ExtractW3CContext(new Dictionary<string, string>
        {
            ["traceparent"] = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01-extra",
        });
        Assert.Equal("", pc.TraceID);
        Assert.Equal("", pc.SpanID);
        Assert.Equal("", pc.Traceparent);
    }
}
