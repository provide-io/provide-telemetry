// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Collections;
using System.Text.Json;

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// The nesting-depth ceiling in hardening.
/// </summary>
/// <remarks>
/// The rule is a cross-language contract, not a local preference: a composite
/// that <em>reaches</em> the ceiling collapses to <see cref="Pii.Redacted"/>,
/// exactly as <c>typescript/src/harden.ts</c>, <c>go/harden.go</c> and
/// <c>rust/src/harden.rs</c> do. Every container kind gets its own case because
/// each one carries its own depth increment: dictionaries, non-generic
/// dictionaries, sequences, JSON objects, JSON arrays and reflected
/// properties/fields all recurse through separate code, and a ceiling that is
/// only proven through one of them says nothing about the other five.
/// <para>
/// The ceilings here are deliberately small and never the default 8, so a
/// caller-supplied depth that is silently discarded in favour of the default
/// shows up as a failure rather than as an accident that happens to agree.
/// </para>
/// </remarks>
[Collection("Telemetry")]
public class HardeningDepthTests
{
    public HardeningDepthTests() => Testing.ResetForTests();

    /// <summary>Nest <paramref name="levels"/> dictionaries over a leaf string.</summary>
    private static object Nest(int levels)
    {
        object node = "leaf";
        for (var i = 0; i < levels; i++)
        {
            node = new Dictionary<string, object?> { ["n"] = node };
        }
        return node;
    }

    /// <summary>Follow the <c>"n"</c> key down <paramref name="levels"/> times.</summary>
    private static object? Descend(object? node, int levels)
    {
        for (var i = 0; i < levels; i++)
        {
            node = Assert.IsType<Dictionary<string, object?>>(node)["n"];
        }
        return node;
    }

    private sealed class NestedProperty
    {
        public object? Inner { get; init; }
    }

    private sealed class NestedField
    {
        public object? Inner;
    }

    [Fact]
    public void DictionaryAtTheCeilingCollapsesToTheMarker()
    {
        // The TypeScript twin of this case: harden({a:{b:{c:1}}}, {maxDepth:2})
        // === {a: {b: '***'}}. Depths 0 and 1 expand; the dictionary at depth 2
        // is refused, so {c:1} is never walked and never emitted.
        var input = new Dictionary<string, object?>
        {
            ["a"] = new Dictionary<string, object?>
            {
                ["b"] = new Dictionary<string, object?> { ["c"] = 1 },
            },
        };

        var hardened = Assert.IsType<Dictionary<string, object?>>(Pii.Harden(input, maxDepth: 2));
        var a = Assert.IsType<Dictionary<string, object?>>(hardened["a"]);
        Assert.Equal(Pii.Redacted, a["b"]);
    }

    [Fact]
    public void RaisingTheCeilingExpandsWhatItRefused()
    {
        // The complement to the case above, on the same input: the refusal is a
        // function of the ceiling, not of the shape. Without it, a stage that
        // refused everything would look exactly as correct.
        var input = new Dictionary<string, object?>
        {
            ["a"] = new Dictionary<string, object?>
            {
                ["b"] = new Dictionary<string, object?> { ["c"] = 1 },
            },
        };

        var hardened = Assert.IsType<Dictionary<string, object?>>(Pii.Harden(input, maxDepth: 4));
        var a = Assert.IsType<Dictionary<string, object?>>(hardened["a"]);
        var b = Assert.IsType<Dictionary<string, object?>>(a["b"]);
        Assert.Equal(1, b["c"]);
    }

    [Fact]
    public void NonGenericDictionaryNestingCountsTowardTheCeiling()
    {
        // Hashtable takes the untyped IDictionary branch, which increments depth
        // in code of its own.
        var input = new Hashtable
        {
            ["a"] = new Hashtable { ["b"] = new Hashtable { ["c"] = 1 } },
        };

        var hardened = Assert.IsType<Dictionary<string, object?>>(Pii.Harden(input, maxDepth: 2));
        var a = Assert.IsType<Dictionary<string, object?>>(hardened["a"]);
        Assert.Equal(Pii.Redacted, a["b"]);
    }

    [Fact]
    public void ArrayNestingCountsTowardTheCeilingToo()
    {
        // harden([[['deep']]], {maxDepth:2}) === [['***']] in TypeScript.
        // Sequences recurse through their own branch, so an array-only path has
        // to reach the ceiling on its own.
        var input = new object[] { new object[] { new[] { "deep" } } };

        var hardened = Assert.IsType<List<object?>>(Pii.Harden(input, maxDepth: 2));
        var inner = Assert.IsType<List<object?>>(hardened[0]);
        Assert.Equal(Pii.Redacted, inner[0]);
    }

    [Fact]
    public void JsonObjectNestingCountsTowardTheCeiling()
    {
        using var document = JsonDocument.Parse("""{"a":{"b":{"c":1}}}""");

        var hardened = Assert.IsType<Dictionary<string, object?>>(
            Pii.Harden(document.RootElement, maxDepth: 2));
        var a = Assert.IsType<Dictionary<string, object?>>(hardened["a"]);
        Assert.Equal(Pii.Redacted, a["b"]);
    }

    [Fact]
    public void JsonArrayNestingCountsTowardTheCeiling()
    {
        using var document = JsonDocument.Parse("""[[["deep"]]]""");

        var hardened = Assert.IsType<List<object?>>(Pii.Harden(document.RootElement, maxDepth: 2));
        var inner = Assert.IsType<List<object?>>(hardened[0]);
        Assert.Equal(Pii.Redacted, inner[0]);
    }

    [Fact]
    public void ReflectedPropertyNestingCountsTowardTheCeiling()
    {
        var input = new NestedProperty { Inner = new NestedProperty { Inner = "leaf" } };

        var hardened = Assert.IsType<Dictionary<string, object?>>(Pii.Harden(input, maxDepth: 2));
        var inner = Assert.IsType<Dictionary<string, object?>>(hardened["Inner"]);
        Assert.Equal(Pii.Redacted, inner["Inner"]);
    }

    [Fact]
    public void ReflectedFieldNestingCountsTowardTheCeiling()
    {
        // Fields recurse through a second loop in FromObject; a secret one level
        // too deep in a field is as exposed as one in a property.
        var input = new NestedField { Inner = new NestedField { Inner = "leaf" } };

        var hardened = Assert.IsType<Dictionary<string, object?>>(Pii.Harden(input, maxDepth: 2));
        var inner = Assert.IsType<Dictionary<string, object?>>(hardened["Inner"]);
        Assert.Equal(Pii.Redacted, inner["Inner"]);
    }

    [Fact]
    public void PastTheCeilingTheRestOfTheTreeIsNeverWalked()
    {
        // The regression an unbounded stage allows: a caller hands in a
        // structure far deeper than the ceiling and gets the whole of it back,
        // so the renderer and the exporter walk all fifty levels.
        var hardened = Pii.Harden(Nest(50), maxDepth: 3);

        Assert.IsType<Dictionary<string, object?>>(Descend(hardened, 2));
        Assert.Equal(Pii.Redacted, Descend(hardened, 3));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    public void NonPositiveCeilingFallsBackToTheDefaultRatherThanRefusingEverything(int requested)
    {
        // 0 means "unset" (the TelemetryConfig default for PiiMaxDepth), not
        // "refuse the payload". Taking the request literally would collapse the
        // top-level value itself and every log line with it.
        var hardened = Pii.Harden(Nest(12), requested);

        Assert.IsType<Dictionary<string, object?>>(Descend(hardened, Pii.DefaultMaxDepth - 1));
        Assert.Equal(Pii.Redacted, Descend(hardened, Pii.DefaultMaxDepth));
    }

    [Fact]
    public void SanitizePayloadAppliesTheCallersCeiling()
    {
        // The payload itself is depth 0, so its values start one level down.
        var sanitized = Pii.SanitizePayload(
            new Dictionary<string, object?> { ["n"] = Nest(4) }, enabled: true, maxDepth: 3);

        Assert.IsType<Dictionary<string, object?>>(Descend(sanitized, 2));
        Assert.Equal(Pii.Redacted, Descend(sanitized, 3));
    }

    [Fact]
    public void SanitizePayloadTreatsANonPositiveCeilingAsTheDefault()
    {
        var sanitized = Pii.SanitizePayload(
            new Dictionary<string, object?> { ["n"] = Nest(12) }, enabled: true, maxDepth: 0);

        Assert.IsType<Dictionary<string, object?>>(Descend(sanitized, Pii.DefaultMaxDepth - 1));
        Assert.Equal(Pii.Redacted, Descend(sanitized, Pii.DefaultMaxDepth));
    }

    [Fact]
    public void ADepthRefusalHidesTheSecretsBeneathIt()
    {
        // The point of the ceiling, stated as an outcome: a password one level
        // past it must not appear in the output at all — not redacted in place,
        // not passed through, simply absent with the branch that held it.
        var sanitized = Pii.SanitizePayload(
            new Dictionary<string, object?>
            {
                ["outer"] = new Dictionary<string, object?>
                {
                    ["inner"] = new Dictionary<string, object?> { ["password"] = "hunter2" },
                },
            },
            enabled: true,
            maxDepth: 2);

        var outer = Assert.IsType<Dictionary<string, object?>>(sanitized["outer"]);
        Assert.Equal(Pii.Redacted, outer["inner"]);
        Assert.DoesNotContain("hunter2", JsonSerializer.Serialize(sanitized), StringComparison.Ordinal);
    }
}
