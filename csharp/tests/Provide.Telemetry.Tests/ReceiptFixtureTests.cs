// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Globalization;

using Provide.Telemetry;
using Xunit;
using YamlDotNet.RepresentationModel;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Reproduces every vector in <c>spec/receipt_fixtures.yaml</c>.
/// </summary>
/// <remarks>
/// The digests there were produced by independent implementations — the
/// <c>rfc8785</c> package and Python's <c>hmac</c> — so passing means agreeing
/// with the other four SDKs rather than agreeing with ourselves. The fixture is
/// read at run time rather than transcribed, because a transcribed vector is a
/// copy that can drift.
/// </remarks>
[Collection("Telemetry")]
public class ReceiptFixtureTests
{
    public ReceiptFixtureTests() => Testing.ResetForTests();

    public static TheoryData<string> CaseIds()
    {
        var data = new TheoryData<string>();
        foreach (var id in ReceiptVectors.All.Keys) data.Add(id);
        return data;
    }

    [Theory]
    [MemberData(nameof(CaseIds))]
    public void ReceiptMatchesVector(string caseId)
    {
        var vector = ReceiptVectors.All[caseId];

        Assert.Equal(vector.CanonicalJson, CanonicalJson.Serialize(vector.Normalized));

        var receipt = Receipts.SignAt(
            vector.Input, vector.Key, vector.ReceiptId, vector.Timestamp, vector.FieldPath, vector.Action);

        Assert.Equal(vector.OriginalHash, receipt.OriginalHash);
        Assert.Equal(vector.Payload, Receipts.Payload(
            vector.ReceiptId, vector.Timestamp, vector.FieldPath, vector.Action, vector.OriginalHash));
        Assert.Equal(vector.Signature, receipt.Hmac);
    }

    [Fact]
    public void EveryFixtureCaseIsExercised()
    {
        // A vector nobody runs is a vector that cannot fail; the fixture file is
        // the contract, so the count is asserted rather than assumed.
        Assert.Equal(7, ReceiptVectors.All.Count);
    }

    [Fact]
    public void NumbersAndTheirStringSpellingsHashDifferently()
    {
        // The reason canonicalization exists: ToString() would render 1 and "1"
        // identically, and a receipt could not tell the two apart.
        var number = Receipts.SignAt(1L, "k", "id", "ts", "f", "redact");
        var text = Receipts.SignAt("1", "k", "id", "ts", "f", "redact");
        Assert.NotEqual(number.OriginalHash, text.OriginalHash);
    }

    [Fact]
    public void AnUnsignedReceiptHasAnEmptySignature()
    {
        var receipt = Receipts.SignAt("value", "", "id", "ts", "f", "redact");
        Assert.Equal("", receipt.Hmac);
        Assert.NotEqual("", receipt.OriginalHash);
    }
}

/// <summary>One case from <c>spec/receipt_fixtures.yaml</c>.</summary>
internal sealed record ReceiptVector(
    string Id,
    string Key,
    object? Input,
    object? Normalized,
    string CanonicalJson,
    string ReceiptId,
    string Timestamp,
    string FieldPath,
    string Action,
    string OriginalHash,
    string Payload,
    string Signature);

/// <summary>Loads the shared receipt vectors.</summary>
internal static class ReceiptVectors
{
    public static readonly IReadOnlyDictionary<string, ReceiptVector> All = Load();

    private static Dictionary<string, ReceiptVector> Load()
    {
        var yaml = new YamlStream();
        using (var reader = new StreamReader(FindFixtures()))
        {
            yaml.Load(reader);
        }

        var root = (YamlMappingNode)yaml.Documents[0].RootNode;
        var cases = (YamlSequenceNode)root["cases"];
        var loaded = new Dictionary<string, ReceiptVector>(StringComparer.Ordinal);
        foreach (var entry in cases.Cast<YamlMappingNode>())
        {
            var id = Scalar(entry, "id");
            loaded[id] = new ReceiptVector(
                id,
                Scalar(entry, "key"),
                Convert(entry["input"]),
                Convert(entry["normalized"]),
                Scalar(entry, "canonical_json"),
                Scalar(entry, "receipt_id"),
                Scalar(entry, "timestamp"),
                Scalar(entry, "field_path"),
                Scalar(entry, "action"),
                Scalar(entry, "original_hash"),
                Scalar(entry, "payload"),
                Scalar(entry, "signature"));
        }
        return loaded;
    }

    private static string Scalar(YamlMappingNode node, string key) => ((YamlScalarNode)node[key]).Value!;

    /// <summary>
    /// Turn a YAML node into the CLR shape a caller would have passed.
    /// </summary>
    /// <remarks>
    /// Scalars are typed by their YAML style and spelling: a quoted scalar is a
    /// string, an unquoted one is parsed as bool, null, integer or double. Doing
    /// this by hand rather than through a deserializer keeps the number/string
    /// distinction the vectors exist to test.
    /// </remarks>
    private static object? Convert(YamlNode node)
    {
        switch (node)
        {
            case YamlMappingNode map:
                {
                    var result = new Dictionary<string, object?>(StringComparer.Ordinal);
                    foreach (var (key, value) in map.Children)
                    {
                        result[((YamlScalarNode)key).Value!] = Convert(value);
                    }
                    return result;
                }
            case YamlSequenceNode sequence:
                return sequence.Children.Select(Convert).ToList();
            case YamlScalarNode scalar:
                return ConvertScalar(scalar);
            default:
                return null;
        }
    }

    private static object? ConvertScalar(YamlScalarNode scalar)
    {
        var text = scalar.Value ?? "";
        if (scalar.Style is YamlDotNet.Core.ScalarStyle.SingleQuoted or YamlDotNet.Core.ScalarStyle.DoubleQuoted)
        {
            return text;
        }
        return text switch
        {
            "" or "null" or "~" => null,
            "true" => true,
            "false" => false,
            ".nan" => double.NaN,
            ".inf" or "+.inf" => double.PositiveInfinity,
            "-.inf" => double.NegativeInfinity,
            _ => ParseNumberOrString(text),
        };
    }

    private static object ParseNumberOrString(string text)
    {
        // An integer literal stays an integer: rendering 1 as 1.0 would change
        // the canonical JSON and therefore the digest.
        if (!text.Contains('.', StringComparison.Ordinal)
            && long.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out var integer))
        {
            return integer;
        }
        if (double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out var real))
        {
            // "-0.0" round-trips to negative zero only through the sign check;
            // double.TryParse already preserves it, and the fixture pins that it
            // must canonicalize to "0".
            return real;
        }
        return text;
    }

    private static string FindFixtures()
    {
        foreach (var candidate in Candidates())
        {
            if (File.Exists(candidate)) return candidate;
        }
        throw new FileNotFoundException("spec/receipt_fixtures.yaml not found from " + AppContext.BaseDirectory);
    }

    private static IEnumerable<string> Candidates()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            yield return Path.Combine(directory.FullName, "spec", "receipt_fixtures.yaml");
            directory = directory.Parent;
        }
    }
}
