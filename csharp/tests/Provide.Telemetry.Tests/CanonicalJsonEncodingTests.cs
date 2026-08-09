// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Collections;

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// RFC 8785 encoding cases the receipt fixtures do not reach: the mutable-map
/// branch, the string escapes, the remaining numeric types, and values JCS
/// cannot encode at all.
/// </summary>
/// <remarks>
/// Every assertion is on the exact output string, because the whole point of
/// canonical JSON is that two implementations produce identical bytes — a test
/// that merely checked "some JSON came back" would pass against an encoder that
/// disagrees with every other SDK.
/// </remarks>
[Collection("Telemetry")]
public class CanonicalJsonEncodingTests
{
    [Fact]
    public void AMutableOnlyMapIsEncodedLikeAnyOtherObject()
    {
        var map = new MutableOnlyMap
        {
            ["b"] = 2,
            ["a"] = 1,
        };

        Assert.Equal("""{"a":1,"b":2}""", CanonicalJson.Serialize(map));
    }

    [Theory]
    // The two mandatory escapes plus every named C0 shorthand. Emitting the
    // raw control byte, or a \\u form where a shorthand exists, would be valid
    // JSON and the wrong bytes.
    [InlineData("\"", @"""\""""")]
    [InlineData("\\", @"""\\""")]
    [InlineData("\b", @"""\b""")]
    [InlineData("\f", @"""\f""")]
    [InlineData("\n", @"""\n""")]
    [InlineData("\r", @"""\r""")]
    [InlineData("\t", @"""\t""")]
    public void NamedEscapesUseTheirShorthandForm(string input, string expected)
    {
        Assert.Equal(expected, CanonicalJson.Serialize(input));
    }

    [Theory]
    // Controls without a shorthand take the four-digit lowercase-hex form.
    // Uppercase hex would be equally valid JSON and a different byte string.
    [InlineData('\u0000', "\"\\u0000\"")]
    [InlineData('\u0001', "\"\\u0001\"")]
    [InlineData('\u001f', "\"\\u001f\"")]
    public void UnnamedControlCharactersUseLowercaseHexEscapes(char c, string expected)
    {
        Assert.Equal(expected, CanonicalJson.Serialize(c.ToString()));
    }

    [Theory]
    // Everything at or above U+0020 is literal, including astral-plane
    // characters: escaping them would change the UTF-8 bytes and therefore the
    // digest every other SDK computes.
    [InlineData(" ")]
    [InlineData("é")]
    [InlineData("🙂")]
    [InlineData("/")]
    public void NonControlCharactersAreEmittedLiterally(string input)
    {
        Assert.Equal($"\"{input}\"", CanonicalJson.Serialize(input));
    }

    [Fact]
    public void UnsignedLongsBeyondTheSignedRangeKeepTheirFullValue()
    {
        // A cast through long would wrap; ulong needs its own branch.
        Assert.Equal("18446744073709551615", CanonicalJson.Serialize(ulong.MaxValue));
        Assert.Equal("0", CanonicalJson.Serialize((ulong)0));
    }

    [Fact]
    public void DecimalsAreEncodedThroughTheirDoubleValue()
    {
        Assert.Equal("1.5", CanonicalJson.Serialize(1.5m));
        Assert.Equal("2", CanonicalJson.Serialize(2.0m));
    }

    [Fact]
    public void FloatsAreEncodedThroughTheirDoubleValue()
    {
        Assert.Equal("1.5", CanonicalJson.Serialize(1.5f));
        Assert.Equal("2", CanonicalJson.Serialize(2.0f));
    }

    [Theory]
    [InlineData(sbyte.MinValue, "-128")]
    [InlineData((short)-1, "-1")]
    [InlineData((ushort)7, "7")]
    [InlineData(uint.MaxValue, "4294967295")]
    public void EveryIntegralTypeGoesThroughTheInt64Path(object value, string expected)
    {
        Assert.Equal(expected, CanonicalJson.Serialize(value));
    }

    [Theory]
    // JSON has no encoding for these, and the cross-language fixture fixes null
    // as the spelling rather than leaving each SDK to invent one.
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(double.NegativeInfinity)]
    public void NonFiniteNumbersBecomeNull(double value)
    {
        Assert.Equal("null", CanonicalJson.Serialize(value));
    }

    [Fact]
    public void ValuesWithNoJcsEncodingBecomeNullRatherThanThrowing()
    {
        // Canonicalization runs inside the redaction path, where an exception
        // would turn a log call into a fault. Hardening normally reduces such
        // values first; this is the belt to that braces.
        Assert.Equal("null", CanonicalJson.Serialize(new DateTime(2026, 8, 7)));
        Assert.Equal("null", CanonicalJson.Serialize(Guid.Empty));
        Assert.Equal("null", CanonicalJson.Serialize(new object()));
    }

    [Theory]
    // ECMAScript stays decimal down to 1e-6 and only then goes exponential;
    // .NET's "R" crosses over earlier, so the reshaping has to be explicit.
    [InlineData(0.00001, "0.00001")]
    [InlineData(0.000001, "0.000001")]
    [InlineData(1e-7, "1e-7")]
    [InlineData(1.5e-7, "1.5e-7")]
    [InlineData(1e21, "1e+21")]
    [InlineData(1.5e21, "1.5e+21")]
    public void ExponentThresholdsMatchEcmaScript(double value, string expected)
    {
        Assert.Equal(expected, CanonicalJson.Serialize(value));
    }

    [Fact]
    public void NegativeZeroCollapsesToZero()
    {
        Assert.Equal("0", CanonicalJson.Serialize(-0.0));
    }

    [Fact]
    public void NestedContainersRecurseThroughEveryBranch()
    {
        var value = new Dictionary<string, object?>
        {
            ["z"] = new List<object?> { null, true, "s", 1, 2.5 },
            ["a"] = new Dictionary<string, object?> { ["inner"] = new object?[] { 1 } },
        };

        Assert.Equal(
            """{"a":{"inner":[1]},"z":[null,true,"s",1,2.5]}""",
            CanonicalJson.Serialize(value));
    }

    [Fact]
    public void EmptyContainersEncodeAsEmptyLiterals()
    {
        Assert.Equal("{}", CanonicalJson.Serialize(new Dictionary<string, object?>()));
        Assert.Equal("[]", CanonicalJson.Serialize(Array.Empty<object?>()));
    }

    /// <summary>A map that implements only the mutable dictionary interface.</summary>
    private sealed class MutableOnlyMap : IDictionary<string, object?>
    {
        private readonly Dictionary<string, object?> _inner = new(StringComparer.Ordinal);

        public object? this[string key] { get => _inner[key]; set => _inner[key] = value; }
        public ICollection<string> Keys => _inner.Keys;
        public ICollection<object?> Values => _inner.Values;
        public int Count => _inner.Count;
        public bool IsReadOnly => false;
        public void Add(string key, object? value) => _inner.Add(key, value);
        public void Add(KeyValuePair<string, object?> item) => _inner.Add(item.Key, item.Value);
        public void Clear() => _inner.Clear();
        public bool Contains(KeyValuePair<string, object?> item) => _inner.Contains(item);
        public bool ContainsKey(string key) => _inner.ContainsKey(key);

        public void CopyTo(KeyValuePair<string, object?>[] array, int arrayIndex) =>
            ((ICollection<KeyValuePair<string, object?>>)_inner).CopyTo(array, arrayIndex);

        public bool Remove(string key) => _inner.Remove(key);
        public bool Remove(KeyValuePair<string, object?> item) => _inner.Remove(item.Key);
        public bool TryGetValue(string key, out object? value) => _inner.TryGetValue(key, out value);
        public IEnumerator<KeyValuePair<string, object?>> GetEnumerator() => _inner.GetEnumerator();
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }
}
