// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// PROVIDE_CONSENT_LEVEL fail-closed semantics. An unset or blank variable is
/// a no-op and a recognised value is applied; a set, non-empty, unrecognised
/// value is an opt-out the operator misspelled, so it fails closed to None and
/// warns once per process on Console.Error, naming the raw value.
/// </summary>
[Collection("Telemetry")]
public class ConsentEnvFailClosedTests : IDisposable
{
    private const string EnvVar = "PROVIDE_CONSENT_LEVEL";

    public ConsentEnvFailClosedTests() => Testing.ResetForTests();

    public void Dispose()
    {
        Environment.SetEnvironmentVariable(EnvVar, null);
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", null);
        Testing.ResetForTests();
    }

    private static string WarningLine(string raw) =>
        "[provide-telemetry] PROVIDE_CONSENT_LEVEL=\"" + raw
        + "\" is not one of FULL, FUNCTIONAL, MINIMAL, NONE; consent set to NONE (fail-closed)"
        + Environment.NewLine;

    private static string CaptureStderr(Action act)
    {
        var sw = new StringWriter();
        var orig = Console.Error;
        Console.SetError(sw);
        try
        {
            act();
        }
        finally
        {
            Console.SetError(orig);
        }
        return sw.ToString();
    }

    [Fact]
    public void InvalidValue_SetsConsentToNone()
    {
        Environment.SetEnvironmentVariable(EnvVar, "NOEN");

        CaptureStderr(Consent.LoadConsentFromEnv);

        Assert.Equal(ConsentLevel.None, Consent.GetConsentLevel());
        Assert.False(Consent.ShouldAllow(Signals.Logs, "ERROR"));
    }

    [Fact]
    public void InvalidValue_OverridesAProgrammaticFull()
    {
        // Fail-closed means None even when code had chosen a more permissive level.
        Consent.SetConsentLevel(ConsentLevel.Full);
        Environment.SetEnvironmentVariable(EnvVar, "NOEN");

        CaptureStderr(Consent.LoadConsentFromEnv);

        Assert.Equal(ConsentLevel.None, Consent.GetConsentLevel());
    }

    [Fact]
    public void InvalidValue_WarnsOnceOnStderrNamingTheRawValue()
    {
        // The raw value is quoted as given — untrimmed — so the operator can see
        // the stray whitespace or the typo that the loader refused.
        Environment.SetEnvironmentVariable(EnvVar, "  noen ");

        var written = CaptureStderr(Consent.LoadConsentFromEnv);

        Assert.Equal(
            "[provide-telemetry] PROVIDE_CONSENT_LEVEL=\"  noen \" is not one of FULL, FUNCTIONAL, MINIMAL, NONE; "
            + "consent set to NONE (fail-closed)" + Environment.NewLine,
            written);
        Assert.Equal(ConsentLevel.None, Consent.GetConsentLevel());
    }

    [Fact]
    public void SecondInvalidLoad_IsSilentButStillFailsClosed()
    {
        // Setup and the lazy logger both call the loader; the operator hears
        // about it once, but silence must not mean the level stops being applied.
        Environment.SetEnvironmentVariable(EnvVar, "BOGUS");

        var first = CaptureStderr(Consent.LoadConsentFromEnv);
        Consent.SetConsentLevel(ConsentLevel.Full);
        var second = CaptureStderr(Consent.LoadConsentFromEnv);

        Assert.Equal(WarningLine("BOGUS"), first);
        Assert.Equal("", second);
        Assert.Equal(ConsentLevel.None, Consent.GetConsentLevel());
    }

    [Fact]
    public void ResetForTests_RearmsTheWarning()
    {
        Environment.SetEnvironmentVariable(EnvVar, "BOGUS");

        var first = CaptureStderr(Consent.LoadConsentFromEnv);
        Testing.ResetForTests();
        var second = CaptureStderr(Consent.LoadConsentFromEnv);

        Assert.Equal(WarningLine("BOGUS"), first);
        Assert.Equal(WarningLine("BOGUS"), second);
    }

    [Theory]
    [InlineData("")]
    [InlineData("  \t ")]
    public void BlankValue_LeavesTheLevelAloneWithoutWarning(string raw)
    {
        // Compose files set VAR= constantly; blank is "unset", not "invalid".
        Consent.SetConsentLevel(ConsentLevel.Minimal);
        Environment.SetEnvironmentVariable(EnvVar, raw);

        var written = CaptureStderr(Consent.LoadConsentFromEnv);

        Assert.Equal("", written);
        Assert.Equal(ConsentLevel.Minimal, Consent.GetConsentLevel());
    }

    [Fact]
    public void RecognisedValue_IsAppliedWithoutWarning()
    {
        Environment.SetEnvironmentVariable(EnvVar, " functional ");

        var written = CaptureStderr(Consent.LoadConsentFromEnv);

        Assert.Equal("", written);
        Assert.Equal(ConsentLevel.Functional, Consent.GetConsentLevel());
    }

    [Fact]
    public void SetupTelemetry_FailsClosedOnInvalidEnv()
    {
        Environment.SetEnvironmentVariable(EnvVar, "NOEN");

        var written = CaptureStderr(() => ProvideTelemetry.SetupTelemetry());

        Assert.Equal(WarningLine("NOEN"), written);
        Assert.Equal(ConsentLevel.None, ProvideTelemetry.GetConsentLevel());
        Assert.False(ProvideTelemetry.ShouldAllow(Signals.Logs, "ERROR"));
    }

    [Fact]
    public void GetLogger_LazyInit_FailsClosedOnInvalidEnv()
    {
        // No SetupTelemetry: the first record a logger emits takes the lazy
        // path, which must read the env before that very record is admitted —
        // so the only thing on stderr is the warning, never the record.
        Environment.SetEnvironmentVariable(EnvVar, "NOEN");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");

        var written = CaptureStderr(
            () => ProvideTelemetry.GetLogger("lazy-consent-invalid").Info("lazy.invalid.should.block"));

        Assert.Equal(WarningLine("NOEN"), written);
        Assert.DoesNotContain("lazy.invalid.should.block", written);
        Assert.Equal(ConsentLevel.None, ProvideTelemetry.GetConsentLevel());
        Assert.False(ProvideTelemetry.ShouldAllow(Signals.Logs, "ERROR"));
    }
}
