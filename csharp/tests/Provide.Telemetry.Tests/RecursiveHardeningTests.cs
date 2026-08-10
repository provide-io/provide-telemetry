// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text.Json;
using System.Text.Json.Nodes;

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

[Collection("Telemetry")]
public class RecursiveHardeningTests
{
    public RecursiveHardeningTests() => Testing.ResetForTests();

    private sealed class SecretPoco
    {
        public string Password { get; init; } = "secret-property";
        public string Public = "ok";
    }

    private sealed class ThrowingPoco
    {
        public string Boom => throw new InvalidOperationException("getter exploded");
    }

    private static string Json(object? value) => JsonSerializer.Serialize(value);

    [Fact]
    public void HardeningTraversesListsJsonPocosAndCycles()
    {
        var cycle = new Dictionary<string, object?>();
        cycle["self"] = cycle;
        var input = new object[]
        {
            new SecretPoco(),
            JsonNode.Parse("{\"token\":\"secret-json\"}")!,
            cycle,
        };

        var hardened = (List<object?>)Pii.Harden(input)!;

        var cycleNode = (Dictionary<string, object?>)hardened[2]!;
        Assert.Equal(Pii.Redacted, cycleNode["self"]);

        var sanitized = Pii.SanitizePayload(
            new Dictionary<string, object?> { ["payload"] = input }, enabled: true, maxDepth: 8);
        Assert.DoesNotContain("secret-property", Json(sanitized), StringComparison.Ordinal);
        Assert.DoesNotContain("secret-json", Json(sanitized), StringComparison.Ordinal);
    }

    [Fact]
    public void PocoPropertiesAndFieldsBothBecomeVisible()
    {
        var hardened = (Dictionary<string, object?>)Pii.Harden(new SecretPoco())!;
        Assert.Equal("secret-property", hardened["Password"]);
        Assert.Equal("ok", hardened["Public"]);
    }

    [Fact]
    public void SensitiveKeysInsideAListOfObjectsAreRedacted()
    {
        // The old traversal descended into Dictionary<string, object?> and
        // nothing else, so a list of records walked straight past redaction.
        var payload = new Dictionary<string, object?>
        {
            ["users"] = new List<object?>
            {
                new Dictionary<string, object?> { ["name"] = "ada", ["password"] = "hunter2" },
            },
        };

        var sanitized = Pii.SanitizePayload(payload, enabled: true, maxDepth: 8);
        Assert.DoesNotContain("hunter2", Json(sanitized), StringComparison.Ordinal);
    }

    [Fact]
    public void SensitiveKeysInsideAJsonElementAreRedacted()
    {
        using var document = JsonDocument.Parse("{\"api_key\":\"live-key-value\"}");
        var payload = new Dictionary<string, object?> { ["body"] = document.RootElement };
        var sanitized = Pii.SanitizePayload(payload, enabled: true, maxDepth: 8);
        Assert.DoesNotContain("live-key-value", Json(sanitized), StringComparison.Ordinal);
    }

    [Fact]
    public void SensitiveKeysInsideAPocoAreRedacted()
    {
        var payload = new Dictionary<string, object?> { ["account"] = new SecretPoco() };
        var sanitized = Pii.SanitizePayload(payload, enabled: true, maxDepth: 8);
        var account = (Dictionary<string, object?>)sanitized["account"]!;
        Assert.Equal(Pii.Redacted, account["Password"]);
        Assert.Equal("ok", account["Public"]);
    }

    [Fact]
    public void AThrowingPropertyGetterIsRedactedRatherThanPropagated()
    {
        var hardened = (Dictionary<string, object?>)Pii.Harden(new ThrowingPoco())!;
        Assert.Equal(Pii.Redacted, hardened["Boom"]);
    }

    [Fact]
    public void DepthBeyondTheLimitCollapsesToTheSentinel()
    {
        object? nested = "leaf";
        for (var i = 0; i < 12; i++)
        {
            nested = new Dictionary<string, object?> { ["next"] = nested };
        }

        var hardened = Json(Pii.Harden(nested, maxDepth: 3));
        Assert.Contains(Pii.Redacted, hardened, StringComparison.Ordinal);
        Assert.DoesNotContain("leaf", hardened, StringComparison.Ordinal);
    }

    [Fact]
    public void SelfReferentialListsTerminate()
    {
        var list = new List<object?>();
        list.Add(list);
        var hardened = (List<object?>)Pii.Harden(list)!;
        Assert.Equal(Pii.Redacted, hardened[0]);
    }

    [Fact]
    public void ASubtreeSharedBetweenTwoKeysIsExpandedOnce()
    {
        // The seen set is walk-scoped, not path-scoped: the second occurrence
        // of the same composite anywhere in the walk collapses to the
        // placeholder. Matches Python's
        // test_a_subtree_shared_between_two_keys_is_expanded_once, TypeScript's
        // never-deleted WeakSet, and Go's never-removed identity set — an
        // n-times-shared subtree must not expand n-fold.
        var shared = new Dictionary<string, object?> { ["k"] = "v" };
        var payload = new Dictionary<string, object?> { ["a"] = shared, ["b"] = shared };
        var hardened = (Dictionary<string, object?>)Pii.Harden(payload)!;
        Assert.Equal("v", ((Dictionary<string, object?>)hardened["a"]!)["k"]);
        Assert.Equal(Pii.Redacted, hardened["b"]);
    }

    [Fact]
    public void SharedSubtreeMaskingIsPerWalkNotPerProcess()
    {
        // The identity set is created per Harden call: a subtree already seen
        // by one walk must expand fully in the next.
        var shared = new Dictionary<string, object?> { ["k"] = "v" };
        var first = (Dictionary<string, object?>)Pii.Harden(
            new Dictionary<string, object?> { ["a"] = shared })!;
        var second = (Dictionary<string, object?>)Pii.Harden(
            new Dictionary<string, object?> { ["a"] = shared })!;
        Assert.Equal("v", ((Dictionary<string, object?>)first["a"]!)["k"]);
        Assert.Equal("v", ((Dictionary<string, object?>)second["a"]!)["k"]);
    }

    [Fact]
    public void MaskingIsByIdentityNotEquality()
    {
        // Two distinct subtrees that merely look alike both survive: the set
        // compares references, not values.
        var payload = new Dictionary<string, object?>
        {
            ["a"] = new Dictionary<string, object?> { ["k"] = "v" },
            ["b"] = new Dictionary<string, object?> { ["k"] = "v" },
        };
        var hardened = (Dictionary<string, object?>)Pii.Harden(payload)!;
        Assert.Equal("v", ((Dictionary<string, object?>)hardened["a"]!)["k"]);
        Assert.Equal("v", ((Dictionary<string, object?>)hardened["b"]!)["k"]);
    }

    [Fact]
    public void NonStringDictionaryKeysBecomeStrings()
    {
        var payload = new Dictionary<string, object?>
        {
            ["counts"] = new Dictionary<int, string> { [7] = "seven" },
        };
        var hardened = (Dictionary<string, object?>)Pii.Harden(payload)!;
        Assert.Equal("seven", ((Dictionary<string, object?>)hardened["counts"]!)["7"]);
    }

    [Fact]
    public void HardeningRunsBeforeRedactionEvenWhenSanitizeIsOff()
    {
        // A renderer must never receive a raw caller object, whatever the
        // sanitize switch says: hardening is about being able to serialize
        // safely, redaction is about what to hide.
        var (payload, redactions) = Pii.SanitizeHardened(
            Pii.HardenPayload(new Dictionary<string, object?> { ["account"] = new SecretPoco() }, 8),
            enabled: false);
        Assert.IsType<Dictionary<string, object?>>(payload["account"]);
        Assert.Empty(redactions);
    }
}
