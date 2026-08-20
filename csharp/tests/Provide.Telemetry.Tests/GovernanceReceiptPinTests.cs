// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text.RegularExpressions;

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Pins the governance and receipt literals the mutation report showed were
/// unasserted: the consent level table and its env-var name, the receipt
/// timestamp format, and the sink-missing diagnostic.
/// </summary>
[Collection("Telemetry")]
public class GovernanceReceiptPinTests : IDisposable
{
    public GovernanceReceiptPinTests() => Testing.ResetForTests();

    public void Dispose()
    {
        Environment.SetEnvironmentVariable("PROVIDE_CONSENT_LEVEL", null);
        Testing.ResetForTests();
    }

    [Theory]
    [InlineData("TRACE", 0)]
    [InlineData("DEBUG", 1)]
    [InlineData("INFO", 2)]
    [InlineData("WARNING", 3)]
    [InlineData("WARN", 3)]
    [InlineData("ERROR", 4)]
    [InlineData("CRITICAL", 5)]
    [InlineData("FATAL", 5)]
    // Consent now resolves through the shared parser, so an unrecognised level
    // ranks INFO here as it does everywhere else. It used to rank 0/TRACE. Both
    // sit below the WARN and ERROR gates, so no consent decision changes --
    // asserted directly by UnrecognisedLevelsStayGatedOff below.
    [InlineData("unknown", 2)]
    public void TheLogLevelOrderTableHoldsEveryDocumentedRank(string level, int rank)
    {
        Assert.Equal(rank, Consent.LogOrder(level));
    }

    [Fact]
    public void UnrecognisedLevelsStayGatedOff()
    {
        Consent.SetConsentLevel(ConsentLevel.Functional);
        Assert.False(Consent.ShouldAllow(Signals.Logs, "unknown"));
        Consent.SetConsentLevel(ConsentLevel.Minimal);
        Assert.False(Consent.ShouldAllow(Signals.Logs, "unknown"));
    }

    [Fact]
    public void FatalIsGatedAsCriticalRatherThanDroppedAsUnrecognised()
    {
        // FATAL was absent from the old local table, so it ranked 0 and was
        // dropped by both gates -- the most severe record in the ladder
        // discarded as if it were the least.
        Consent.SetConsentLevel(ConsentLevel.Functional);
        Assert.True(Consent.ShouldAllow(Signals.Logs, "FATAL"));
        Consent.SetConsentLevel(ConsentLevel.Minimal);
        Assert.True(Consent.ShouldAllow(Signals.Logs, "FATAL"));
    }

    [Fact]
    public void FunctionalConsentGatesLogsAtWarningAndMinimalAtError()
    {
        Consent.SetConsentLevel(ConsentLevel.Functional);
        Assert.False(Consent.ShouldAllow(Signals.Logs, "INFO"));
        Assert.True(Consent.ShouldAllow(Signals.Logs, "WARN"));
        Assert.True(Consent.ShouldAllow(Signals.Logs, "WARNING"));

        Consent.SetConsentLevel(ConsentLevel.Minimal);
        Assert.False(Consent.ShouldAllow(Signals.Logs, "WARNING"));
        Assert.True(Consent.ShouldAllow(Signals.Logs, "ERROR"));
    }

    [Fact]
    public void TheConsentEnvVarNameIsReadByLoadConsentFromEnv()
    {
        Environment.SetEnvironmentVariable("PROVIDE_CONSENT_LEVEL", "minimal");

        Consent.LoadConsentFromEnv();

        Assert.Equal(ConsentLevel.Minimal, Consent.GetConsentLevel());
    }

    [Fact]
    public void AClassificationRuleDefaultsToAnEmptyPatternAtInternalClass()
    {
        var rule = new ClassificationRule();

        Assert.Equal("", rule.Pattern);
        Assert.Equal(DataClass.Internal, rule.Class);
    }

    [Fact]
    public void TheMissingSinkErrorExplainsWhatWouldBeDiscarded()
    {
        var ex = new MissingReceiptSinkError();

        Assert.Contains("no IReceiptSink is configured", ex.Message);
        Assert.Contains("discarded", ex.Message);
    }

    [Fact]
    public void ACollectedReceiptCarriesTheFixedWidthUtcTimestamp()
    {
        Receipts.EnableReceipts(true, "test-signing-key", "svc-pin");
        ProvideTelemetry.ReplacePIIRules(
            new[] { new PIIRule { Path = new[] { "user", "ssn" }, Mode = PiiModes.Redact } });
        ProvideTelemetry.GetLogger("pin").Info("user.update.ok", new Dictionary<string, object?>
        {
            ["user"] = new Dictionary<string, object?> { ["ssn"] = "123-45-6789" },
        });

        var receipt = Assert.Single(Receipts.GetEmittedReceiptsForTests());

        Assert.Matches(new Regex(@"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"), receipt.Timestamp);
        Assert.Equal("svc-pin", receipt.ServiceName);
        Assert.NotEqual("", receipt.OriginalHash);
        Assert.NotEqual("", receipt.Hmac);
    }

    [Fact]
    public void TheTestCollectorReportsASuccessfulEmit()
    {
        var collector = new TestReceiptCollector();

        Assert.True(collector.Emit(new RedactionReceipt { ReceiptId = "r-1" }));

        Assert.Equal("r-1", Assert.Single(collector.Receipts).ReceiptId);
    }
}
