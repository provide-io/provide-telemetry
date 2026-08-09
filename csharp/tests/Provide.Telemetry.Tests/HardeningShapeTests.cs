// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Collections;
using System.Text.Json;
using System.Text.Json.Nodes;

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// The shapes hardening has to reduce before redaction can inspect them.
/// </summary>
/// <remarks>
/// Each case asserts the reduced form, not merely that hardening returned:
/// a value that survives as an opaque object is exactly the failure this stage
/// exists to prevent, and it is indistinguishable from success unless the test
/// looks at what came back.
/// </remarks>
[Collection("Telemetry")]
public class HardeningShapeTests
{
    public HardeningShapeTests() => Testing.ResetForTests();

    [Fact]
    public void CharsBecomeSingleCharacterStrings()
    {
        // Left as a char, a value renders as a number in some serializers and a
        // string in others; pinning it to a string makes the wire form the same
        // everywhere.
        Assert.Equal("x", Pii.Harden('x'));
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void BoolsPassThroughUnchanged(bool value)
    {
        Assert.Equal(value, Pii.Harden(value));
    }

    [Fact]
    public void NumericScalarsPassThroughWithTheirOwnTypes()
    {
        Assert.Equal(7, Pii.Harden(7));
        Assert.Equal(7L, Pii.Harden(7L));
        Assert.Equal(7.5, Pii.Harden(7.5));
        Assert.Equal(7.5m, Pii.Harden(7.5m));
        Assert.Equal((byte)7, Pii.Harden((byte)7));
    }

    [Fact]
    public void NullStaysNull()
    {
        Assert.Null(Pii.Harden(null));
    }

    [Theory]
    [MemberData(nameof(StringifiedScalars))]
    public void OpaqueScalarsAreStringifiedInvariantly(object value, string expected)
    {
        // These types carry no readable public state worth traversing, so they
        // become their invariant string form rather than a dictionary of
        // whatever properties the BCL happens to expose.
        Assert.Equal(expected, Pii.Harden(value));
    }

    public static TheoryData<object, string> StringifiedScalars() => new()
    {
        { new DateTime(2026, 8, 7, 12, 0, 0, DateTimeKind.Utc), "08/07/2026 12:00:00" },
        { TimeSpan.FromMinutes(90), "01:30:00" },
        { Guid.Parse("00000000-0000-0000-0000-0000000000ab"), "00000000-0000-0000-0000-0000000000ab" },
        { new Uri("https://example.test/a"), "https://example.test/a" },
        { DayOfWeek.Friday, "Friday" },
    };

    [Fact]
    public void DateTimeOffsetsAreStringifiedToo()
    {
        var value = new DateTimeOffset(2026, 8, 7, 12, 0, 0, TimeSpan.Zero);

        Assert.Equal(value.ToString(System.Globalization.CultureInfo.InvariantCulture), Pii.Harden(value));
    }

    [Fact]
    public void AReadOnlyDictionaryViewIsTraversedLikeAMutableOne()
    {
        var value = Pii.Harden(new ReadOnlyOnlyView(new Dictionary<string, object?>
        {
            ["password"] = "hunter2",
            ["nested"] = new Dictionary<string, object?> { ["depth"] = 1 },
        }));

        var map = Assert.IsType<Dictionary<string, object?>>(value);
        Assert.Equal("hunter2", map["password"]);
        Assert.Equal(1, Assert.IsType<Dictionary<string, object?>>(map["nested"])["depth"]);
    }

    [Fact]
    public void ASensitiveKeyBehindAReadOnlyDictionaryViewIsStillRedacted()
    {
        var sanitized = Pii.SanitizePayload(
            new Dictionary<string, object?>
            {
                ["outer"] = new ReadOnlyOnlyView(
                    new Dictionary<string, object?> { ["password"] = "hunter2" }),
            },
            enabled: true,
            maxDepth: 8);

        var outer = Assert.IsType<Dictionary<string, object?>>(sanitized["outer"]);
        Assert.Equal(Pii.Redacted, outer["password"]);
    }

    // ── JSON trees ───────────────────────────────────────────────────────────

    [Fact]
    public void JsonElementsOfEveryKindReduceToTheirClrShape()
    {
        var document = JsonDocument.Parse(
            """{"list":[1,2.5,"s"],"yes":true,"no":false,"nothing":null}""");

        var map = Assert.IsType<Dictionary<string, object?>>(Pii.Harden(document.RootElement));

        var list = Assert.IsType<List<object?>>(map["list"]);
        // Every JSON number arrives as a double, integral or not: the
        // long/double conditional in FromJsonElement unifies to double, so an
        // integer is widened on the way out. Renderers see 1, not 1.0, because
        // the canonical serializer formats integral doubles without a fraction.
        Assert.Equal(1.0d, Assert.IsType<double>(list[0]));
        Assert.Equal(2.5, list[1]);
        Assert.Equal("s", list[2]);
        Assert.Equal("1", CanonicalJson.Serialize(list[0]));
        Assert.Equal(true, map["yes"]);
        Assert.Equal(false, map["no"]);
        Assert.Null(map["nothing"]);
    }

    [Fact]
    public void JsonArraysReachedThroughANodeAreTraversedAsLists()
    {
        var node = JsonNode.Parse("""[{"password":"hunter2"},"plain"]""")!;

        var list = Assert.IsType<List<object?>>(Pii.Harden(node));

        Assert.Equal(2, list.Count);
        Assert.Equal("hunter2", Assert.IsType<Dictionary<string, object?>>(list[0])["password"]);
        Assert.Equal("plain", list[1]);
    }

    [Fact]
    public void AScalarJsonNodeReducesToItsValue()
    {
        Assert.Equal("plain", Pii.Harden(JsonNode.Parse("\"plain\"")!));
        Assert.Equal(42.0d, Assert.IsType<double>(Pii.Harden(JsonNode.Parse("42")!)));
    }

    // ── failure containment ──────────────────────────────────────────────────

    [Fact]
    public void AnEnumerableThatRefusesToBeEnumeratedCollapsesToTheSentinel()
    {
        // The whole value is reduced, not the log call abandoned: a collection
        // type that throws on iteration is a caller bug, and turning it into a
        // faulted log statement would make telemetry the outage.
        Assert.Equal(Pii.Redacted, Pii.Harden(new HostileSequence()));
    }

    [Fact]
    public void AnEnumerableThatRefusesEnumerationInsideAPayloadRedactsOnlyThatField()
    {
        var sanitized = Pii.SanitizePayload(
            new Dictionary<string, object?> { ["bad"] = new HostileSequence(), ["good"] = "kept" },
            enabled: true,
            maxDepth: 8);

        Assert.Equal(Pii.Redacted, sanitized["bad"]);
        Assert.Equal("kept", sanitized["good"]);
    }

    [Fact]
    public void APropertyThatCannotBeBoxedIsRedactedRatherThanPropagated()
    {
        // Reflection cannot box a ByRef-like value, so reading the property
        // throws NotSupportedException before any user code runs.
        var map = Assert.IsType<Dictionary<string, object?>>(Pii.Harden(new UnboxableProperty()));

        Assert.Equal(Pii.Redacted, map[nameof(UnboxableProperty.Bytes)]);
        Assert.Equal("visible", map[nameof(UnboxableProperty.Ordinary)]);
    }

    /// <summary>A dictionary view that implements only the read-only interface.</summary>
    private sealed class ReadOnlyOnlyView : IReadOnlyDictionary<string, object?>
    {
        private readonly Dictionary<string, object?> _inner;

        public ReadOnlyOnlyView(Dictionary<string, object?> inner) => _inner = inner;

        public object? this[string key] => _inner[key];
        public IEnumerable<string> Keys => _inner.Keys;
        public IEnumerable<object?> Values => _inner.Values;
        public int Count => _inner.Count;
        public bool ContainsKey(string key) => _inner.ContainsKey(key);
        public bool TryGetValue(string key, out object? value) => _inner.TryGetValue(key, out value);
        public IEnumerator<KeyValuePair<string, object?>> GetEnumerator() => _inner.GetEnumerator();
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }

    /// <summary>A sequence that throws the moment anything iterates it.</summary>
    private sealed class HostileSequence : IEnumerable<int>
    {
        public IEnumerator<int> GetEnumerator() => throw new NotSupportedException("no iteration here");
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }

    private sealed class UnboxableProperty
    {
        public ReadOnlySpan<byte> Bytes => default;
        public string Ordinary => "visible";
    }
}
