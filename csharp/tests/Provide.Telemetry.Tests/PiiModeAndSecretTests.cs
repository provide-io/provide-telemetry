// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text.RegularExpressions;

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// The redaction modes the parity fixtures do not reach, custom secret
/// patterns, and the hashing of non-string values.
/// </summary>
[Collection("Telemetry")]
public class PiiModeAndSecretTests
{
    public PiiModeAndSecretTests() => Testing.ResetForTests();

    private static Dictionary<string, object?> Sanitize(Dictionary<string, object?> payload) =>
        Pii.SanitizePayload(payload, enabled: true, maxDepth: 8);

    // ── modes ────────────────────────────────────────────────────────────────

    [Fact]
    public void PassMode_LeavesTheValueAloneAndWritesNoReceipt()
    {
        Receipts.EnableReceipts(true, "key", "svc");
        Pii.RegisterPIIRule(new PIIRule { Path = new[] { "email" }, Mode = PiiModes.Pass });

        var sanitized = Sanitize(new Dictionary<string, object?> { ["email"] = "a@example.test" });

        Assert.Equal("a@example.test", sanitized["email"]);
        Assert.Empty(Receipts.GetEmittedReceiptsForTests());
    }

    [Fact]
    public void PassMode_OverridesTheDefaultSensitiveKeyList()
    {
        // A rule is the caller's explicit decision and must outrank the built-in
        // key list, or an opt-out would be impossible.
        Pii.RegisterPIIRule(new PIIRule { Path = new[] { "token" }, Mode = PiiModes.Pass });

        var sanitized = Sanitize(new Dictionary<string, object?> { ["token"] = "kept" });

        Assert.Equal("kept", sanitized["token"]);
    }

    [Fact]
    public void AnUnrecognisedModeFallsBackToRedaction()
    {
        // Fail closed: a typo in a mode name must not become a data leak.
        Receipts.EnableReceipts(true, "", "svc");
        Pii.RegisterPIIRule(new PIIRule { Path = new[] { "email" }, Mode = "obfuscate" });

        var sanitized = Sanitize(new Dictionary<string, object?> { ["email"] = "a@example.test" });

        Assert.Equal(Pii.Redacted, sanitized["email"]);
        var receipt = Assert.Single(Receipts.GetEmittedReceiptsForTests());
        Assert.Equal("redact", receipt.Action);
        Assert.Equal("email", receipt.FieldPath);
    }

    [Fact]
    public void TruncateModeWithAZeroLimitKeepsOnlyTheSuffixAndReceiptsIt()
    {
        // Zero is a limit, not "no limit": a rule that keeps nothing must not
        // hand the whole value through — and the value did change, so the
        // change is receipted like any other truncation.
        Receipts.EnableReceipts(true, "", "svc");
        Pii.RegisterPIIRule(new PIIRule { Path = new[] { "note" }, Mode = PiiModes.Truncate, TruncateTo = 0 });

        var sanitized = Sanitize(new Dictionary<string, object?> { ["note"] = "a long note" });

        Assert.Equal(Pii.TruncationSuffix, sanitized["note"]);
        Assert.Equal("truncate", Assert.Single(Receipts.GetEmittedReceiptsForTests()).Action);
    }

    [Fact]
    public void TruncateModeWithoutALimitKeepsEightScalarValues()
    {
        Assert.Equal(8, new PIIRule().TruncateTo);
        Assert.Equal(8, Pii.DefaultTruncateTo);
        Pii.RegisterPIIRule(new PIIRule { Path = new[] { "note" }, Mode = PiiModes.Truncate });

        var sanitized = Sanitize(new Dictionary<string, object?> { ["note"] = "abcdefghij" });

        Assert.Equal("abcdefgh" + Pii.TruncationSuffix, sanitized["note"]);
    }

    [Fact]
    public void TruncateModeClampsANegativeLimitToZero()
    {
        Pii.RegisterPIIRule(new PIIRule { Path = new[] { "note" }, Mode = PiiModes.Truncate, TruncateTo = -3 });

        var sanitized = Sanitize(new Dictionary<string, object?> { ["note"] = "hello" });

        Assert.Equal(Pii.TruncationSuffix, sanitized["note"]);
    }

    [Fact]
    public void TruncateModeCountsScalarValuesNotUtf16CodeUnits()
    {
        // Each emoji is one scalar value but two UTF-16 code units. Counting
        // code units would cut the second emoji in half; counting scalar
        // values keeps three whole ones and leaves a three-emoji string alone.
        Pii.RegisterPIIRule(new PIIRule { Path = new[] { "note" }, Mode = PiiModes.Truncate, TruncateTo = 3 });
        Pii.RegisterPIIRule(new PIIRule { Path = new[] { "fits" }, Mode = PiiModes.Truncate, TruncateTo = 3 });

        var sanitized = Sanitize(new Dictionary<string, object?> { ["note"] = "😀😀😀😀😀", ["fits"] = "😀😀😀" });

        Assert.Equal("😀😀😀" + Pii.TruncationSuffix, sanitized["note"]);
        Assert.Equal("😀😀😀", sanitized["fits"]);
    }

    [Fact]
    public void TruncateModeLeavesAnEmptyStringAloneEvenAtLimitZero()
    {
        // Nothing to shorten, so nothing changes and nothing is receipted.
        Receipts.EnableReceipts(true, "", "svc");
        Pii.RegisterPIIRule(new PIIRule { Path = new[] { "note" }, Mode = PiiModes.Truncate, TruncateTo = 0 });

        var sanitized = Sanitize(new Dictionary<string, object?> { ["note"] = "" });

        Assert.Equal("", sanitized["note"]);
        Assert.Empty(Receipts.GetEmittedReceiptsForTests());
    }

    [Fact]
    public void TruncateModeStringifiesANonStringValueFirst()
    {
        Pii.RegisterPIIRule(new PIIRule { Path = new[] { "count" }, Mode = PiiModes.Truncate, TruncateTo = 2 });

        var sanitized = Sanitize(new Dictionary<string, object?> { ["count"] = 123456 });

        Assert.Equal("12" + Pii.TruncationSuffix, sanitized["count"]);
    }

    [Fact]
    public void AlreadyRedactedValuesEarnNoSecondReceipt()
    {
        Receipts.EnableReceipts(true, "", "svc");

        var sanitized = Sanitize(new Dictionary<string, object?> { ["password"] = Pii.Redacted });

        Assert.Equal(Pii.Redacted, sanitized["password"]);
        Assert.Empty(Receipts.GetEmittedReceiptsForTests());
    }

    [Fact]
    public void NonStringScalarsAtOrdinaryKeysPassThroughUntouched()
    {
        var sanitized = Sanitize(new Dictionary<string, object?>
        {
            ["count"] = 42,
            ["ratio"] = 0.5,
            ["enabled"] = true,
            ["missing"] = null,
        });

        Assert.Equal(42, sanitized["count"]);
        Assert.Equal(0.5, sanitized["ratio"]);
        Assert.Equal(true, sanitized["enabled"]);
        Assert.Null(sanitized["missing"]);
    }

    [Fact]
    public void WildcardRulePathsMatchAnySingleSegment()
    {
        Pii.RegisterPIIRule(new PIIRule { Path = new[] { "users", "*", "ssn" }, Mode = PiiModes.Drop });

        var sanitized = Sanitize(new Dictionary<string, object?>
        {
            ["users"] = new Dictionary<string, object?>
            {
                ["u1"] = new Dictionary<string, object?> { ["ssn"] = "111", ["name"] = "a" },
                ["u2"] = new Dictionary<string, object?> { ["ssn"] = "222" },
            },
        });

        var users = Assert.IsType<Dictionary<string, object?>>(sanitized["users"]);
        var u1 = Assert.IsType<Dictionary<string, object?>>(users["u1"]);
        Assert.False(u1.ContainsKey("ssn"));
        Assert.Equal("a", u1["name"]);
        Assert.False(Assert.IsType<Dictionary<string, object?>>(users["u2"]).ContainsKey("ssn"));
    }

    [Fact]
    public void ARulePathOfADifferentLengthDoesNotMatch()
    {
        Pii.RegisterPIIRule(new PIIRule { Path = new[] { "a", "b" }, Mode = PiiModes.Drop });

        var sanitized = Sanitize(new Dictionary<string, object?> { ["a"] = "kept" });

        Assert.Equal("kept", sanitized["a"]);
    }

    // ── custom secret patterns ───────────────────────────────────────────────

    [Fact]
    public void RegisterSecretPattern_MakesDetectSecretInValueRecogniseTheShape()
    {
        var text = "corp-secret-000000000000";
        Assert.False(Pii.DetectSecretInValue(text));

        Pii.RegisterSecretPattern("corp", new Regex("corp-secret-[0-9]+"));

        Assert.True(Pii.DetectSecretInValue(text));
    }

    [Fact]
    public void RegisterSecretPattern_RedactsMatchingValuesInsideAPayload()
    {
        Pii.RegisterSecretPattern("corp", new Regex("corp-secret-[0-9]+"));

        var sanitized = Sanitize(new Dictionary<string, object?>
        {
            ["note"] = "corp-secret-000000000000",
            ["other"] = "an ordinary long sentence",
        });

        Assert.Equal(Pii.Redacted, sanitized["note"]);
        Assert.Equal("an ordinary long sentence", sanitized["other"]);
    }

    [Fact]
    public void CustomPatternsAreForgottenOnReset()
    {
        Pii.RegisterSecretPattern("corp", new Regex("corp-secret-[0-9]+"));

        Testing.ResetForTests();

        Assert.False(Pii.DetectSecretInValue("corp-secret-000000000000"));
    }

    [Theory]
    // Below the minimum length nothing is scanned at all: short strings are
    // where false positives live, and a 19-character value cannot hold any of
    // the built-in credential shapes.
    [InlineData("")]
    [InlineData("abcdef0123456789abc")]
    public void ShortValuesAreNeverTreatedAsSecrets(string text)
    {
        Assert.True(text.Length < Pii.MinSecretLength);
        Assert.False(Pii.DetectSecretInValue(text));
    }

    // ── hashing ──────────────────────────────────────────────────────────────

    [Fact]
    public void HashValue_HashesTheStringItselfNotItsRendering()
    {
        // The string "1" and the number 1 render identically, so a hash over the
        // rendering could not tell the two receipts apart. They must agree here
        // only because the canonical text is the same by definition.
        Assert.Equal(Pii.HashValue("1"), Pii.HashValue(1));
        Assert.NotEqual(Pii.HashValue("1"), Pii.HashValue("2"));
        Assert.Equal(12, Pii.HashValue("anything").Length);
    }

    [Fact]
    public void HashValue_SpellsNullAsItsCanonicalJson()
    {
        // null is a value with a canonical spelling, not an absent string: the
        // digest is sha256("null"), which every SDK agrees on, rather than
        // sha256("") which would collide with the empty string.
        Assert.Equal(Pii.HashValue("null"), Pii.HashValue(null));
        Assert.NotEqual(Pii.HashValue(""), Pii.HashValue(null));
    }

    [Fact]
    public void HashValue_SpellsNonStringsAsCanonicalJson()
    {
        // RFC 8785 fixes the text that is hashed, so neither a machine's
        // decimal separator nor .NET's capitalised Boolean.ToString() can give
        // a different digest from the other SDKs for the same value.
        Assert.Equal(Pii.HashValue("1.5"), Pii.HashValue(1.5));
        Assert.Equal(Pii.HashValue("true"), Pii.HashValue(true));
        Assert.NotEqual(Pii.HashValue("True"), Pii.HashValue(true));
        Assert.Equal(
            Pii.HashValue("{\"a\":\"x\",\"b\":1}"),
            Pii.HashValue(new Dictionary<string, object?> { ["b"] = 1, ["a"] = "x" }));
    }

    [Fact]
    public void HashMode_ReplacesTheValueWithItsDigestAndReceiptsIt()
    {
        Receipts.EnableReceipts(true, "", "svc");
        Pii.RegisterPIIRule(new PIIRule { Path = new[] { "user_id" }, Mode = PiiModes.Hash });

        var sanitized = Sanitize(new Dictionary<string, object?> { ["user_id"] = 4242 });

        Assert.Equal(Pii.HashValue(4242), sanitized["user_id"]);
        Assert.Equal("hash", Assert.Single(Receipts.GetEmittedReceiptsForTests()).Action);
    }

    // ── rule storage ─────────────────────────────────────────────────────────

    [Fact]
    public void RegisteredRulesAreCopiedSoLaterMutationCannotWeakenThem()
    {
        var rule = new PIIRule { Path = new[] { "email" }, Mode = PiiModes.Drop };
        Pii.RegisterPIIRule(rule);

        rule.Mode = PiiModes.Pass;
        rule.Path = new[] { "other" };

        Assert.False(Sanitize(new Dictionary<string, object?> { ["email"] = "a@b.test" })
            .ContainsKey("email"));
        var stored = Assert.Single(Pii.GetPIIRules());
        Assert.Equal(PiiModes.Drop, stored.Mode);
        Assert.Equal(new[] { "email" }, stored.Path);
    }

    [Fact]
    public void SanitizePayload_RejectsANullPayload()
    {
        Assert.Throws<ArgumentNullException>(
            () => Pii.SanitizePayload(null!, enabled: true, maxDepth: 8));
    }

    [Fact]
    public void SanitizePayload_DisabledReturnsTheHardenedPayloadUnredacted()
    {
        var sanitized = Pii.SanitizePayload(
            new Dictionary<string, object?> { ["password"] = "hunter2" },
            enabled: false,
            maxDepth: 8);

        Assert.Equal("hunter2", sanitized["password"]);
    }

    [Fact]
    public void ANonPositiveDepthFallsBackToTheDefaultRatherThanFlatteningEverything()
    {
        var payload = new Dictionary<string, object?>
        {
            ["a"] = new Dictionary<string, object?> { ["b"] = new Dictionary<string, object?> { ["c"] = 1 } },
        };

        var sanitized = Pii.SanitizePayload(payload, enabled: true, maxDepth: 0);

        var a = Assert.IsType<Dictionary<string, object?>>(sanitized["a"]);
        var b = Assert.IsType<Dictionary<string, object?>>(a["b"]);
        Assert.Equal(1, b["c"]);
    }

    [Fact]
    public void HardenWithANonPositiveDepthAlsoFallsBackToTheDefault()
    {
        var nested = new Dictionary<string, object?>
        {
            ["a"] = new Dictionary<string, object?> { ["b"] = 1 },
        };

        var hardened = Assert.IsType<Dictionary<string, object?>>(Pii.Harden(nested, maxDepth: -1));

        Assert.Equal(1, Assert.IsType<Dictionary<string, object?>>(hardened["a"])["b"]);
    }
}
