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
}
