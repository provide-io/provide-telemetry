// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text.Json;

using Provide.Telemetry;
using Xunit;
using YamlDotNet.RepresentationModel;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Reproduces every vector in <c>spec/jcs_number_fixtures.yaml</c>.
/// </summary>
/// <remarks>
/// <para>
/// One vector per branch of the ECMAScript <c>Number::toString</c> algorithm
/// that RFC 8785 defers to. They exist because <c>spec/receipt_fixtures.yaml</c>'s
/// seven whole receipts are realistic payloads, and realistic payloads never
/// reach the exponent thresholds, the significand-trimming path, or the
/// zero-padding branch — so two real bugs shipped past them. Python rendered
/// <c>1e21</c> as <c>"0.1"</c>, colliding with <c>0.1</c> and <c>1e22</c> on a
/// single receipt digest, and this SDK rendered <c>1e-6</c> as <c>"1e-6"</c>
/// where every other one emits <c>"0.000001"</c> — .NET's "R" and "G17" formats
/// switch to exponential notation several orders of magnitude earlier than
/// ECMAScript does, so the divergence was invisible until a vector pinned it.
/// </para>
/// <para>
/// Each case is asserted twice: the number rendered alone, and the same number
/// inside <c>{"v": ...}</c>. A serializer can format correctly in isolation and
/// still lose the value in context.
/// </para>
/// </remarks>
[Collection("Telemetry")]
public class JcsNumberFixtureTests
{
    public JcsNumberFixtureTests() => Testing.ResetForTests();

    public static TheoryData<string> CaseIds()
    {
        var data = new TheoryData<string>();
        foreach (var id in JcsNumberVectors.All.Keys) data.Add(id);
        return data;
    }

    [Fact]
    public void EveryCommittedVectorIsExercised()
    {
        // Asserted before the theories are trusted: a parse that yielded nothing
        // would make MemberData empty, and an empty theory is a vacuous pass.
        Assert.True(
            JcsNumberVectors.All.Count >= JcsNumberVectors.ExpectedCases,
            $"loaded {JcsNumberVectors.All.Count} vectors, want at least {JcsNumberVectors.ExpectedCases}");
    }

    [Theory]
    [MemberData(nameof(CaseIds))]
    public void NumberRendersToItsCanonicalForm(string caseId)
    {
        var vector = JcsNumberVectors.All[caseId];
        Assert.Equal(vector.Canonical, CanonicalJson.Serialize(vector.Value));
    }

    [Theory]
    [MemberData(nameof(CaseIds))]
    public void NumberRendersTheSameInsideAnObject(string caseId)
    {
        var vector = JcsNumberVectors.All[caseId];
        var wrapped = new Dictionary<string, object?>(StringComparer.Ordinal) { ["v"] = vector.Value };
        Assert.Equal(vector.InObject, CanonicalJson.Serialize(wrapped));
    }
}

/// <summary>One case from <c>spec/jcs_number_fixtures.yaml</c>.</summary>
/// <param name="Id">Stable identifier.</param>
/// <param name="Branch">The branch of Number::toString this vector covers.</param>
/// <param name="Value">The binary64 the vector is about.</param>
/// <param name="Canonical">The number rendered on its own.</param>
/// <param name="InObject">The same number inside <c>{"v": ...}</c>.</param>
internal sealed record JcsNumberVector(
    string Id,
    string Branch,
    double Value,
    string Canonical,
    string InObject);

/// <summary>Loads the shared JCS number vectors.</summary>
internal static class JcsNumberVectors
{
    /// <summary>The committed vector count, one per branch of Number::toString.</summary>
    public const int ExpectedCases = 21;

    public static readonly IReadOnlyDictionary<string, JcsNumberVector> All = Load();

    private static Dictionary<string, JcsNumberVector> Load()
    {
        var yaml = new YamlStream();
        using (var reader = new StreamReader(FindFixtures()))
        {
            yaml.Load(reader);
        }

        var root = (YamlMappingNode)yaml.Documents[0].RootNode;
        var cases = (YamlSequenceNode)root["cases"];
        var loaded = new Dictionary<string, JcsNumberVector>(StringComparer.Ordinal);
        foreach (var entry in cases.Cast<YamlMappingNode>())
        {
            var id = Scalar(entry, "id");
            var inObject = Scalar(entry, "in_object");
            loaded[id] = new JcsNumberVector(
                id,
                Scalar(entry, "branch"),
                ValueOf(inObject),
                Scalar(entry, "canonical"),
                inObject);
        }
        return loaded;
    }

    private static string Scalar(YamlMappingNode node, string key) => ((YamlScalarNode)node[key]).Value!;

    /// <summary>
    /// Recover the binary64 the vector describes from its <c>in_object</c> form.
    /// </summary>
    /// <remarks>
    /// <c>GetDouble</c> rather than the element's natural CLR type: JavaScript
    /// has a single number type, so the fixture spells <c>1e20</c> and
    /// <c>1e21</c> without a decimal point exactly as <c>JSON.stringify</c>
    /// renders them, and a value read as <c>long</c> would take
    /// <c>CanonicalJson</c>'s integer path and never reach the ECMAScript
    /// number formatter these vectors exist to pin. The object form is rebuilt
    /// from this same double for the same reason.
    /// </remarks>
    private static double ValueOf(string inObject)
    {
        using var document = JsonDocument.Parse(inObject);
        return document.RootElement.GetProperty("v").GetDouble();
    }

    private static string FindFixtures()
    {
        foreach (var candidate in Candidates())
        {
            if (File.Exists(candidate)) return candidate;
        }
        throw new FileNotFoundException("spec/jcs_number_fixtures.yaml not found from " + AppContext.BaseDirectory);
    }

    /// <summary>
    /// Walk up from the test binary rather than counting directories: the output
    /// path depends on the target framework and configuration, and a mutation
    /// runner may relocate the tree entirely.
    /// </summary>
    private static IEnumerable<string> Candidates()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            yield return Path.Combine(directory.FullName, "spec", "jcs_number_fixtures.yaml");
            directory = directory.Parent;
        }
    }
}
