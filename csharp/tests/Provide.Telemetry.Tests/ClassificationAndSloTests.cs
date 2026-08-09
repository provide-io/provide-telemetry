// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>Data-classification rules and the classification policy.</summary>
[Collection("Telemetry")]
public class ClassificationTests
{
    public ClassificationTests() => Testing.ResetForTests();

    [Fact]
    public void ClassifyKey_UnmatchedKeyIsUnclassifiedRatherThanPublic()
    {
        // null, not DataClass.Public: "no rule said anything" and "a rule said
        // this is public" are different facts, and the policy acts on them the
        // same way only by coincidence.
        Assert.Null(Classification.ClassifyKey("anything"));
    }

    [Fact]
    public void RegisterClassificationRules_ReplacesTheWholeRuleSet()
    {
        Classification.RegisterClassificationRule(
            new ClassificationRule { Pattern = "ssn", Class = DataClass.Restricted });

        Classification.RegisterClassificationRules(new[]
        {
            new ClassificationRule { Pattern = "email", Class = DataClass.Confidential },
        });

        Assert.Equal(DataClass.Confidential, Classification.ClassifyKey("email"));
        Assert.Null(Classification.ClassifyKey("ssn"));
    }

    [Fact]
    public void RegisterClassificationRule_AppendsToTheExistingSet()
    {
        Classification.RegisterClassificationRule(
            new ClassificationRule { Pattern = "ssn", Class = DataClass.Restricted });
        Classification.RegisterClassificationRule(
            new ClassificationRule { Pattern = "email", Class = DataClass.Confidential });

        Assert.Equal(DataClass.Restricted, Classification.ClassifyKey("ssn"));
        Assert.Equal(DataClass.Confidential, Classification.ClassifyKey("email"));
    }

    [Fact]
    public void RegisterClassificationRule_CopiesTheRuleSoLaterMutationCannotReclassify()
    {
        var rule = new ClassificationRule { Pattern = "ssn", Class = DataClass.Restricted };
        Classification.RegisterClassificationRule(rule);

        rule.Pattern = "harmless";
        rule.Class = DataClass.Public;

        Assert.Equal(DataClass.Restricted, Classification.ClassifyKey("ssn"));
        Assert.Null(Classification.ClassifyKey("harmless"));
    }

    [Theory]
    [InlineData("ssn", DataClass.Restricted)]
    [InlineData("SSN", DataClass.Restricted)]
    [InlineData("Ssn", DataClass.Restricted)]
    public void ClassifyKey_ExactPatternsMatchCaseInsensitively(string key, DataClass expected)
    {
        Classification.RegisterClassificationRule(
            new ClassificationRule { Pattern = "ssn", Class = DataClass.Restricted });

        Assert.Equal(expected, Classification.ClassifyKey(key));
    }

    [Theory]
    [InlineData("card_number", DataClass.Secret)]
    [InlineData("CARD_expiry", DataClass.Secret)]
    [InlineData("card_", DataClass.Secret)]
    public void ClassifyKey_TrailingStarMatchesAnyPrefixedKey(string key, DataClass expected)
    {
        Classification.RegisterClassificationRule(
            new ClassificationRule { Pattern = "card_*", Class = DataClass.Secret });

        Assert.Equal(expected, Classification.ClassifyKey(key));
    }

    [Fact]
    public void ClassifyKey_PrefixRuleDoesNotMatchAShorterKey()
    {
        Classification.RegisterClassificationRule(
            new ClassificationRule { Pattern = "card_*", Class = DataClass.Secret });

        Assert.Null(Classification.ClassifyKey("card"));
    }

    [Fact]
    public void ClassifyKey_FirstMatchingRuleWins()
    {
        Classification.RegisterClassificationRules(new[]
        {
            new ClassificationRule { Pattern = "card_*", Class = DataClass.Internal },
            new ClassificationRule { Pattern = "card_number", Class = DataClass.Secret },
        });

        Assert.Equal(DataClass.Internal, Classification.ClassifyKey("card_number"));
    }

    [Fact]
    public void GetClassificationPolicy_DefaultsEscalateWithSensitivity()
    {
        var policy = Classification.GetClassificationPolicy();

        Assert.Equal("pass", policy.PublicAction);
        Assert.Equal("pass", policy.InternalAction);
        Assert.Equal("redact", policy.ConfidentialAction);
        Assert.Equal("drop", policy.RestrictedAction);
        Assert.Equal("drop", policy.SecretAction);
    }

    [Fact]
    public void SetClassificationPolicy_RoundTripsEveryFieldAndCopiesBothWays()
    {
        var installed = new ClassificationPolicy
        {
            PublicAction = "pass",
            InternalAction = "redact",
            ConfidentialAction = "hash",
            RestrictedAction = "truncate",
            SecretAction = "drop",
        };
        Classification.SetClassificationPolicy(installed);

        // Mutating the caller's object, or the returned one, must not reach the
        // stored policy: a governance rule that a later assignment can loosen
        // is not a rule.
        installed.SecretAction = "pass";
        var first = Classification.GetClassificationPolicy();
        first.ConfidentialAction = "pass";
        var second = Classification.GetClassificationPolicy();

        Assert.Equal("redact", second.InternalAction);
        Assert.Equal("hash", second.ConfidentialAction);
        Assert.Equal("truncate", second.RestrictedAction);
        Assert.Equal("drop", second.SecretAction);
    }

    [Fact]
    public void ResetForTests_ClearsRulesAndRestoresTheDefaultPolicy()
    {
        Classification.RegisterClassificationRule(
            new ClassificationRule { Pattern = "ssn", Class = DataClass.Restricted });
        Classification.SetClassificationPolicy(new ClassificationPolicy { SecretAction = "pass" });

        Testing.ResetForTests();

        Assert.Null(Classification.ClassifyKey("ssn"));
        Assert.Equal("drop", Classification.GetClassificationPolicy().SecretAction);
    }
}

/// <summary>Consent decisions and the SLO metric helpers.</summary>
[Collection("Telemetry")]
public class ConsentAndSloTests
{
    public ConsentAndSloTests() => Testing.ResetForTests();

    [Fact]
    public void ShouldAllow_UnknownConsentLevelDeniesEverything()
    {
        // A value outside the enum can only come from a corrupted or
        // forward-versioned setting; denying is the safe reading of "I do not
        // know what this permits".
        Consent.SetConsentLevel((ConsentLevel)99);

        Assert.False(Consent.ShouldAllow(Signals.Logs, "CRITICAL"));
        Assert.False(Consent.ShouldAllow(Signals.Traces, ""));
        Assert.False(Consent.ShouldAllow(Signals.Metrics, ""));
        Assert.False(Consent.ShouldAllow(Signals.Context, ""));
    }

    [Theory]
    [InlineData("TRACE", false)]
    [InlineData("DEBUG", false)]
    [InlineData("INFO", false)]
    [InlineData("WARN", true)]
    [InlineData("WARNING", true)]
    [InlineData("ERROR", true)]
    [InlineData("CRITICAL", true)]
    [InlineData("nonsense", false)]
    public void ShouldAllow_FunctionalAdmitsWarningAndAbove(string level, bool expected)
    {
        // An unrecognised level ranks below TRACE, so a typo suppresses the line
        // rather than promoting it past the consent gate.
        Consent.SetConsentLevel(ConsentLevel.Functional);

        Assert.Equal(expected, Consent.ShouldAllow(Signals.Logs, level));
    }

    [Theory]
    [InlineData("WARNING", false)]
    [InlineData("ERROR", true)]
    [InlineData("CRITICAL", true)]
    public void ShouldAllow_MinimalAdmitsErrorAndAbove(string level, bool expected)
    {
        Consent.SetConsentLevel(ConsentLevel.Minimal);

        Assert.Equal(expected, Consent.ShouldAllow(Signals.Logs, level));
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("PARTIAL")]
    public void LoadConsentFromEnv_LeavesTheLevelAloneForUnrecognisedValues(string raw)
    {
        Consent.SetConsentLevel(ConsentLevel.Minimal);
        Environment.SetEnvironmentVariable("PROVIDE_CONSENT_LEVEL", raw);
        try
        {
            Consent.LoadConsentFromEnv();

            Assert.Equal(ConsentLevel.Minimal, Consent.GetConsentLevel());
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_CONSENT_LEVEL", null);
        }
    }

    [Theory]
    [InlineData("full", ConsentLevel.Full)]
    [InlineData(" FUNCTIONAL ", ConsentLevel.Functional)]
    [InlineData("Minimal", ConsentLevel.Minimal)]
    [InlineData("none", ConsentLevel.None)]
    public void LoadConsentFromEnv_TrimsAndUppercasesBeforeMatching(string raw, ConsentLevel expected)
    {
        // Start from a level the case under test is not, so a no-op parse fails.
        Consent.SetConsentLevel(expected == ConsentLevel.Full ? ConsentLevel.None : ConsentLevel.Full);
        Environment.SetEnvironmentVariable("PROVIDE_CONSENT_LEVEL", raw);
        try
        {
            Consent.LoadConsentFromEnv();

            Assert.Equal(expected, Consent.GetConsentLevel());
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_CONSENT_LEVEL", null);
        }
    }

    // ── Slo.ClassifyError ────────────────────────────────────────────────────

    [Fact]
    public void ClassifyError_NullIsUnknownAndAnUnrecognisedTypeIsError()
    {
        Assert.Equal("unknown", Slo.ClassifyError(null));
        Assert.Equal("error", Slo.ClassifyError(new InvalidOperationException("boom")));
        Assert.Equal("auth", Slo.ClassifyError(new UnauthorizedAccessException()));
        // ConfigurationError before its TelemetryError base: the more specific
        // classification has to win, or every config fault reads as "error".
        Assert.Equal("config", Slo.ClassifyError(new ConfigurationError("bad")));
        Assert.Equal("error", Slo.ClassifyError(new TelemetryError("bad")));
    }

    // ── Slo metric helpers ───────────────────────────────────────────────────

    [Fact]
    public void RecordRedMetrics_EmitsTheRequestCounterAndTheDurationHistogram()
    {
        // The sampler override keys on the instrument name, so silencing one
        // name and counting what is left pins which instruments were used —
        // a renamed metric shows up as a changed count, not as a silent pass.
        SilenceMetric("provide.slo.red.requests");

        Slo.RecordRedMetrics("checkout", 12.5, success: true);

        // One emission left: the duration histogram. The drop count is not
        // asserted here because a sampling rejection is currently recorded
        // twice — once in Sampling.ShouldSample and again in
        // SignalPipeline.Reject — so it would pin an accounting quirk rather
        // than the instrument identity this test is about.
        Assert.Equal(1, Health.GetHealthSnapshot().MetricsEmitted);
    }

    [Fact]
    public void RecordRedMetrics_EmitsBothInstrumentsWhenNothingIsSilenced()
    {
        Slo.RecordRedMetrics("checkout", 12.5, success: false);

        Assert.Equal(2, Health.GetHealthSnapshot().MetricsEmitted);
    }

    [Fact]
    public void RecordUseMetrics_EmitsUtilisationSaturationAndErrors()
    {
        SilenceMetric("provide.slo.use.saturation");

        Slo.RecordUseMetrics("db-pool", utilization: 0.8, saturation: 0.2, errors: 3);

        // Utilisation and errors survive; saturation is the one silenced by name.
        Assert.Equal(2, Health.GetHealthSnapshot().MetricsEmitted);
    }

    [Fact]
    public void SloHelpers_EmitNothingWhenConsentForbidsMetrics()
    {
        Consent.SetConsentLevel(ConsentLevel.None);

        Slo.RecordRedMetrics("checkout", 1.0, success: true);
        Slo.RecordUseMetrics("db-pool", 0.1, 0.2, 0.3);

        var health = Health.GetHealthSnapshot();
        Assert.Equal(0, health.MetricsEmitted);
        Assert.Equal(5, health.MetricsDropped);
    }

    private static void SilenceMetric(string name)
    {
        // Setup first: the lazy init the first Metrics call would otherwise
        // trigger reapplies the config's sampling policy and would erase the
        // override on its way past.
        ProvideTelemetry.SetupTelemetry();
        Sampling.SetSamplingPolicy(Signals.Metrics, new SamplingPolicy
        {
            DefaultRate = 1.0,
            Overrides = new Dictionary<string, double> { [name] = 0.0 },
        });
    }
}
