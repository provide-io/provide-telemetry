// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// The parts of W3C propagation the parity fixtures do not reach: the header
/// sequence overload, baggage parsing, context binding, and injection.
/// </summary>
[Collection("Telemetry")]
public class PropagationExtractionTests
{
    private const string Traceparent = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01";
    private const string TraceId = "0af7651916cd43dd8448eb211c80319c";
    private const string SpanId = "b7ad6b7169203331";

    public PropagationExtractionTests() => Testing.ResetForTests();

    // ── header sources ───────────────────────────────────────────────────────

    [Fact]
    public void ExtractW3CContext_AcceptsAHeaderSequenceWithRepeatedAndMixedCaseNames()
    {
        // ASGI/HTTP header collections are sequences of pairs, not maps, and
        // arrive in whatever casing the peer chose. The last value for a name
        // wins, which is what a dictionary build from the sequence must do.
        var headers = new List<KeyValuePair<string, string>>
        {
            new("Traceparent", "00-11111111111111111111111111111111-2222222222222222-01"),
            new("TRACEPARENT", Traceparent),
            new("TraceState", "vendor=1"),
            new("Baggage", "tenant=acme"),
        };

        var pc = Propagation.ExtractW3CContext(headers);

        Assert.Equal(TraceId, pc.TraceID);
        Assert.Equal(SpanId, pc.SpanID);
        Assert.Equal("vendor=1", pc.Tracestate);
        Assert.Equal("tenant=acme", pc.Baggage);
    }

    [Fact]
    public void ExtractW3CContext_FindsHeadersInACaseSensitiveMapByScanningIt()
    {
        // A caller may hand us an ordinal dictionary, where the direct lookups
        // all miss. The scan is the fallback that keeps a capitalised header
        // from silently dropping the whole incoming trace.
        var headers = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["Traceparent"] = Traceparent,
            ["Tracestate"] = "vendor=1",
            ["Baggage"] = "tenant=acme",
        };

        var pc = Propagation.ExtractW3CContext(headers);

        Assert.Equal(Traceparent, pc.Traceparent);
        Assert.Equal(TraceId, pc.TraceID);
        Assert.Equal("vendor=1", pc.Tracestate);
        Assert.Equal("tenant=acme", pc.Baggage);
    }

    [Fact]
    public void ExtractW3CContext_NoHeadersYieldsAnEmptyContext()
    {
        var pc = Propagation.ExtractW3CContext(new Dictionary<string, string>());

        Assert.Equal("", pc.Traceparent);
        Assert.Equal("", pc.Tracestate);
        Assert.Equal("", pc.Baggage);
        Assert.Equal("", pc.TraceID);
        Assert.Equal("", pc.SpanID);
    }

    [Theory]
    // An all-zero identifier is the W3C "invalid" sentinel. Accepting one would
    // graft every request onto a single fabricated trace.
    [InlineData("00-00000000000000000000000000000000-b7ad6b7169203331-01")]
    [InlineData("00-0af7651916cd43dd8448eb211c80319c-0000000000000000-01")]
    public void ExtractW3CContext_RejectsAllZeroIdentifiersAndClearsTheHeader(string header)
    {
        var pc = Propagation.ExtractW3CContext(
            new Dictionary<string, string> { ["traceparent"] = header });

        Assert.Equal("", pc.TraceID);
        Assert.Equal("", pc.SpanID);
        Assert.Equal("", pc.Traceparent);
    }

    [Theory]
    [InlineData("ff-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")]
    [InlineData("FF-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")]
    public void ExtractW3CContext_RejectsTheReservedVersionFf(string header)
    {
        // W3C trace-context forbids version ff: trusting it would adopt a
        // trace identity from an invalid header. Python rejects it too.
        var pc = Propagation.ExtractW3CContext(
            new Dictionary<string, string> { ["traceparent"] = header });

        Assert.Equal("", pc.TraceID);
        Assert.Equal("", pc.SpanID);
        Assert.Equal("", pc.Traceparent);
    }

    [Theory]
    [InlineData(" 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")]
    [InlineData("00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01 ")]
    [InlineData("\t00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")]
    public void ExtractW3CContext_RejectsSurroundingWhitespace(string header)
    {
        // The header is a fixed 55-character token; tolerating whitespace here
        // diverged from every other runtime, which all reject it.
        var pc = Propagation.ExtractW3CContext(
            new Dictionary<string, string> { ["traceparent"] = header });

        Assert.Equal("", pc.TraceID);
        Assert.Equal("", pc.SpanID);
    }

    [Fact]
    public void ExtractW3CContext_UppercaseHexIsNormalisedToLowercase()
    {
        var pc = Propagation.ExtractW3CContext(new Dictionary<string, string>
        {
            ["traceparent"] = "00-0AF7651916CD43DD8448EB211C80319C-B7AD6B7169203331-01",
        });

        Assert.Equal(TraceId, pc.TraceID);
        Assert.Equal(SpanId, pc.SpanID);
    }

    [Fact]
    public void ExtractW3CContext_OversizedSinglePairTracestateIsDiscardedOnBytesNotPairCount()
    {
        // One pair, so the 32-pair guard says nothing; the 512-byte guard is
        // what has to reject it.
        var state = "vendor=" + new string('v', 600);

        var pc = Propagation.ExtractW3CContext(
            new Dictionary<string, string> { ["tracestate"] = state });

        Assert.Equal("", pc.Tracestate);
    }

    // ── baggage parsing ──────────────────────────────────────────────────────

    [Fact]
    public void ParseBaggage_ReadsCommaSeparatedPairsAndDropsMetadata()
    {
        var parsed = Propagation.ParseBaggage("tenant=acme,region=eu;ttl=30, user = u1 ");

        Assert.Equal(
            new Dictionary<string, string> { ["tenant"] = "acme", ["region"] = "eu", ["user"] = "u1" },
            parsed);
    }

    [Theory]
    // No "=" at all; an "=" in position zero, so there is no key; a key that is
    // only whitespace; and a key with a character outside the token grammar.
    [InlineData("novalue")]
    [InlineData("=value")]
    [InlineData(" =value")]
    [InlineData("bad key=value")]
    [InlineData("")]
    public void ParseBaggage_SkipsMembersItCannotParse(string raw)
    {
        Assert.Empty(Propagation.ParseBaggage(raw));
    }

    [Fact]
    public void ParseBaggage_KeepsTheGoodMembersOfAPartlyMalformedList()
    {
        var parsed = Propagation.ParseBaggage("novalue,tenant=acme,=orphan,bad key=v");

        Assert.Equal(new Dictionary<string, string> { ["tenant"] = "acme" }, parsed);
    }

    [Fact]
    public void ParseBaggage_StripsControlCharactersFromValues()
    {
        // A newline in a baggage value would otherwise forge a second log line
        // once the value is bound into the context and rendered.
        var parsed = Propagation.ParseBaggage("tenant=acm\ne");

        Assert.Equal("acme", parsed["tenant"]);
    }

    [Fact]
    public void ParseBaggage_KeysAreCaseSensitive()
    {
        var parsed = Propagation.ParseBaggage("Tenant=upper,tenant=lower");

        Assert.Equal("upper", parsed["Tenant"]);
        Assert.Equal("lower", parsed["tenant"]);
    }

    // ── binding ──────────────────────────────────────────────────────────────

    [Fact]
    public void BindPropagationContext_BindsBaggageBothWholeAndPerMember()
    {
        var pc = Propagation.ExtractW3CContext(new Dictionary<string, string>
        {
            ["traceparent"] = Traceparent,
            ["baggage"] = "tenant=acme,region=eu",
        });

        Propagation.BindPropagationContext(pc);

        var bound = Context.GetBoundFields();
        Assert.Equal("tenant=acme,region=eu", bound["baggage"]);
        Assert.Equal("acme", bound["baggage.tenant"]);
        Assert.Equal("eu", bound["baggage.region"]);
        Assert.Equal((TraceId, SpanId), Context.GetTraceContext());
        Assert.Equal(Traceparent, Context.GetPropagationContext().Traceparent);
    }

    [Fact]
    public void BindPropagationContext_EmptyContextBindsNothingAtAll()
    {
        var pc = Propagation.ExtractW3CContext(new Dictionary<string, string>());

        Propagation.BindPropagationContext(pc);

        Assert.Empty(Context.GetBoundFields());
        Assert.Equal(("", ""), Context.GetTraceContext());
        // The propagation slot is still published, so a caller can tell "bound an
        // empty context" from "never bound one".
        Assert.Equal("", Context.GetPropagationContext().Traceparent);
    }

    [Fact]
    public void BindPropagationContext_SpanIdWithoutTraceIdStillSetsTheTraceSlot()
    {
        Propagation.BindPropagationContext(new PropagationContext { SpanID = SpanId });

        Assert.Equal(("", SpanId), Context.GetTraceContext());
    }

    // ── injection ────────────────────────────────────────────────────────────

    [Fact]
    public void InjectTraceparent_WritesTheSampledCanonicalHeader()
    {
        Context.SetTraceContext(TraceId, SpanId);
        var headers = new Dictionary<string, string>();

        Propagation.InjectTraceparent(headers);

        Assert.Equal(Traceparent, headers["traceparent"]);
    }

    [Theory]
    // A half-populated context cannot produce a valid header, and emitting one
    // with an empty field would poison the downstream service's trace.
    [InlineData("", "")]
    [InlineData(TraceId, "")]
    [InlineData("", SpanId)]
    public void InjectTraceparent_WritesNothingWithoutBothIdentifiers(string traceId, string spanId)
    {
        Context.SetTraceContext(traceId, spanId);
        var headers = new Dictionary<string, string>();

        Propagation.InjectTraceparent(headers);

        Assert.Empty(headers);
    }

    [Fact]
    public void InjectTraceparent_RoundTripsThroughExtraction()
    {
        Context.SetTraceContext(TraceId, SpanId);
        var headers = new Dictionary<string, string>();
        Propagation.InjectTraceparent(headers);

        var pc = Propagation.ExtractW3CContext(headers);

        Assert.Equal(TraceId, pc.TraceID);
        Assert.Equal(SpanId, pc.SpanID);
    }
}
