// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>Attribute cardinality guards, including TTL expiry.</summary>
[Collection("Telemetry")]
public class CardinalityGuardTests
{
    public CardinalityGuardTests() => Testing.ResetForTests();

    [Fact]
    public void UnregisteredKeysPassThroughUntouched()
    {
        Cardinality.RegisterCardinalityLimit("route", new CardinalityLimit { MaxValues = 1, TtlSeconds = 60 });

        var guarded = Cardinality.GuardAttributes(new Dictionary<string, string>
        {
            ["route"] = "/a",
            ["method"] = "GET",
            ["status"] = "200",
        });

        // Only registered keys are bounded; guarding everything would silently
        // drop labels an operator never asked to limit.
        Assert.Equal("/a", guarded["route"]);
        Assert.Equal("GET", guarded["method"]);
        Assert.Equal("200", guarded["status"]);
    }

    [Fact]
    public void ARepeatedValueIsAdmittedWithoutConsumingAnotherSlot()
    {
        Cardinality.RegisterCardinalityLimit("route", new CardinalityLimit { MaxValues = 2, TtlSeconds = 60 });

        var first = Cardinality.GuardAttributes(new Dictionary<string, string> { ["route"] = "/a" });
        var repeat = Cardinality.GuardAttributes(new Dictionary<string, string> { ["route"] = "/a" });
        var second = Cardinality.GuardAttributes(new Dictionary<string, string> { ["route"] = "/b" });

        Assert.Equal("/a", first["route"]);
        Assert.Equal("/a", repeat["route"]);
        // The repeat did not spend the second slot, so /b still fits.
        Assert.Equal("/b", second["route"]);
    }

    [Fact]
    public void LimitsAreClampedToAtLeastOneValueAndOneSecond()
    {
        Cardinality.RegisterCardinalityLimit("route", new CardinalityLimit { MaxValues = 0, TtlSeconds = 0 });

        var stored = Cardinality.GetCardinalityLimits()["route"];

        Assert.Equal(1, stored.MaxValues);
        Assert.Equal(1.0, stored.TtlSeconds);
        // A zero limit would sentinel every value, making the label useless.
        Assert.Equal("/a", Cardinality.GuardAttributes(
            new Dictionary<string, string> { ["route"] = "/a" })["route"]);
    }

    [Fact]
    public void ReRegisteringAKeyForgetsTheValuesSeenUnderTheOldLimit()
    {
        Cardinality.RegisterCardinalityLimit("route", new CardinalityLimit { MaxValues = 1, TtlSeconds = 60 });
        Cardinality.GuardAttributes(new Dictionary<string, string> { ["route"] = "/a" });
        Assert.Equal("__overflow__", Cardinality.GuardAttributes(
            new Dictionary<string, string> { ["route"] = "/b" })["route"]);

        Cardinality.RegisterCardinalityLimit("route", new CardinalityLimit { MaxValues = 1, TtlSeconds = 60 });

        Assert.Equal("/b", Cardinality.GuardAttributes(
            new Dictionary<string, string> { ["route"] = "/b" })["route"]);
    }

    [Fact]
    public void GetCardinalityLimitsHandsBackCopies()
    {
        Cardinality.RegisterCardinalityLimit("route", new CardinalityLimit { MaxValues = 3, TtlSeconds = 60 });

        Cardinality.GetCardinalityLimits()["route"].MaxValues = 99;

        Assert.Equal(3, Cardinality.GetCardinalityLimits()["route"].MaxValues);
    }

    [Fact]
    public void ExpiredValuesAreEvictedSoTheBudgetRecovers()
    {
        // The TTL is the whole point of the guard: a service whose route set
        // genuinely changes over time must not be sentinelled forever because
        // of paths it stopped serving an hour ago. One second is the clamped
        // floor, which is why this test sleeps rather than mocking a clock.
        Cardinality.RegisterCardinalityLimit("route", new CardinalityLimit { MaxValues = 1, TtlSeconds = 1 });
        Assert.Equal("/a", Cardinality.GuardAttributes(
            new Dictionary<string, string> { ["route"] = "/a" })["route"]);
        Assert.Equal("__overflow__", Cardinality.GuardAttributes(
            new Dictionary<string, string> { ["route"] = "/b" })["route"]);

        Thread.Sleep(TimeSpan.FromMilliseconds(1200));

        // /a has aged out, freeing the single slot for /b.
        Assert.Equal("/b", Cardinality.GuardAttributes(
            new Dictionary<string, string> { ["route"] = "/b" })["route"]);
        Assert.Equal("__overflow__", Cardinality.GuardAttributes(
            new Dictionary<string, string> { ["route"] = "/a" })["route"]);
    }
}

/// <summary>The per-signal export circuit breaker.</summary>
[Collection("Telemetry")]
public class CircuitBreakerTests
{
    public CircuitBreakerTests() => Testing.ResetForTests();

    [Fact]
    public void AnUnknownSignalHasNoBreakerAndIsAlwaysAllowed()
    {
        // GetCircuitState is reachable from the health snapshot for any name; a
        // signal with no breaker reports the safe, permissive answer rather
        // than faulting a status call.
        Assert.Equal("closed", Resilience.GetCircuitState("bogus"));
        Assert.Equal(0, Resilience.GetCircuitOpenCount("bogus"));
        Assert.True(Resilience.AllowAttempt("bogus"));
    }

    [Fact]
    public void ThreeConsecutiveTimeoutsTripTheBreakerOpen()
    {
        for (var i = 0; i < 2; i++)
        {
            Resilience.RecordFailure(Signals.Logs, isTimeout: true);
            Assert.Equal("closed", Resilience.GetCircuitState(Signals.Logs));
            Assert.True(Resilience.AllowAttempt(Signals.Logs));
        }

        Resilience.RecordFailure(Signals.Logs, isTimeout: true);

        Assert.Equal("open", Resilience.GetCircuitState(Signals.Logs));
        Assert.Equal(1, Resilience.GetCircuitOpenCount(Signals.Logs));
        // An open breaker sheds load: no attempt is permitted until the
        // cooldown elapses.
        Assert.False(Resilience.AllowAttempt(Signals.Logs));
    }

    [Fact]
    public void ANonTimeoutFailureResetsTheRunTowardsTripping()
    {
        // The breaker exists to shed load from a saturated exporter pool; a
        // collector answering 4xx immediately is not saturating anything.
        Resilience.RecordFailure(Signals.Traces, isTimeout: true);
        Resilience.RecordFailure(Signals.Traces, isTimeout: true);
        Resilience.RecordFailure(Signals.Traces, isTimeout: false);
        Resilience.RecordFailure(Signals.Traces, isTimeout: true);

        Assert.Equal("closed", Resilience.GetCircuitState(Signals.Traces));
        Assert.Equal(0, Resilience.GetCircuitOpenCount(Signals.Traces));
    }

    [Fact]
    public void ASuccessResetsTheRunTowardsTripping()
    {
        Resilience.RecordFailure(Signals.Metrics, isTimeout: true);
        Resilience.RecordFailure(Signals.Metrics, isTimeout: true);

        Resilience.RecordSuccess(Signals.Metrics);
        Resilience.RecordFailure(Signals.Metrics, isTimeout: true);

        Assert.Equal("closed", Resilience.GetCircuitState(Signals.Metrics));
    }

    [Fact]
    public void BreakerStateIsPerSignal()
    {
        for (var i = 0; i < 3; i++) Resilience.RecordFailure(Signals.Logs, isTimeout: true);

        var health = Health.GetHealthSnapshot();
        Assert.Equal("open", health.LogsCircuitState);
        Assert.Equal(1, health.LogsCircuitOpenCount);
        Assert.Equal("closed", health.TracesCircuitState);
        Assert.Equal("closed", health.MetricsCircuitState);
    }

    [Fact]
    public void RecordingAgainstAnUnknownSignalIsANoOp()
    {
        Resilience.RecordFailure("bogus", isTimeout: true);
        Resilience.RecordSuccess("bogus");

        Assert.Equal("closed", Resilience.GetCircuitState("bogus"));
    }

    [Fact]
    public void ResetClosesEveryBreakerAndRestoresTheDefaultPolicies()
    {
        for (var i = 0; i < 3; i++) Resilience.RecordFailure(Signals.Logs, isTimeout: true);
        Resilience.SetExporterPolicy(Signals.Logs, new ExporterPolicy { Retries = 5 });

        Testing.ResetForTests();

        Assert.Equal("closed", Resilience.GetCircuitState(Signals.Logs));
        Assert.Equal(0, Resilience.GetCircuitOpenCount(Signals.Logs));
        Assert.Equal(0, Resilience.GetExporterPolicy(Signals.Logs).Retries);
    }

    [Fact]
    public void ExporterPolicyValuesAreClampedToTheirLegalRanges()
    {
        Resilience.SetExporterPolicy(Signals.Logs, new ExporterPolicy
        {
            Retries = -1,
            BackoffSeconds = -1.0,
            TimeoutSeconds = -1.0,
        });

        var stored = Resilience.GetExporterPolicy(Signals.Logs);
        Assert.Equal(0, stored.Retries);
        Assert.Equal(0.0, stored.BackoffSeconds);
        Assert.Equal(0.0, stored.TimeoutSeconds);

        Resilience.SetExporterPolicy(Signals.Logs, new ExporterPolicy { Retries = 10_000 });
        Assert.Equal(Resilience.MaxExportAttempts - 1, Resilience.GetExporterPolicy(Signals.Logs).Retries);
    }

    [Fact]
    public void ExporterPolicyRejectsNullAndUnknownSignals()
    {
        Assert.Throws<ArgumentNullException>(
            () => Resilience.SetExporterPolicy(Signals.Logs, null!));

        var error = Assert.Throws<ConfigurationError>(
            () => Resilience.SetExporterPolicy("bogus", new ExporterPolicy()));
        Assert.Equal(
            "unknown signal \"bogus\", expected one of [logs, metrics, traces]", error.Message);
        Assert.Throws<ConfigurationError>(() => Resilience.GetExporterPolicy("bogus"));
    }
}

/// <summary>The reconfigure result DTO.</summary>
[Collection("Telemetry")]
public class ReconfigureResultTests
{
    [Fact]
    public void DefaultsDescribeAnUnappliedReadyResult()
    {
        var result = new ReconfigureResult();

        Assert.False(result.Applied);
        Assert.Null(result.Previous);
        Assert.Null(result.Current);
        Assert.Equal("", result.Error);
        Assert.Equal(RuntimeState.Ready, result.State);
    }

    [Fact]
    public void EveryFieldRoundTrips()
    {
        var previous = TelemetryConfig.Default();
        var current = TelemetryConfig.Default();
        current.ServiceName = "after";

        var result = new ReconfigureResult
        {
            Applied = true,
            Previous = previous,
            Current = current,
            Error = "partial",
            State = RuntimeState.Degraded,
        };

        Assert.True(result.Applied);
        Assert.Same(previous, result.Previous);
        Assert.Equal("after", result.Current!.ServiceName);
        Assert.Equal("partial", result.Error);
        Assert.Equal(RuntimeState.Degraded, result.State);
    }
}
