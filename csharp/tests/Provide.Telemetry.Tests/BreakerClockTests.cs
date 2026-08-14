// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Drives the circuit breaker's cooldown and half-open transitions through a
/// fake <see cref="TimeProvider"/> — the paths a real clock only reaches after
/// a 30-second-plus cooldown, which is why they were the recorded coverage
/// exception until this seam existed.
/// </summary>
[Collection("Telemetry")]
public class BreakerClockTests : IDisposable
{
    /// <summary>Manually advanced timestamp source at the system frequency.</summary>
    private sealed class FakeClock : TimeProvider
    {
        private long _timestamp;

        public override long GetTimestamp() => _timestamp;

        public void Advance(TimeSpan by) =>
            _timestamp += (long)(by.TotalSeconds * TimestampFrequency);
    }

    private readonly FakeClock _clock = new();

    public BreakerClockTests()
    {
        Testing.ResetForTests();
        Resilience.Clock = _clock;
    }

    public void Dispose() => Testing.ResetForTests();

    private static void TripBreaker(string signal)
    {
        for (var i = 0; i < Resilience.CircuitBreakerThreshold; i++)
        {
            Resilience.RecordFailure(signal, isTimeout: true);
        }
    }

    [Fact]
    public void ATrippedBreakerOpensAndBlocksUntilTheCooldownElapses()
    {
        TripBreaker(Signals.Logs);

        Assert.Equal("open", Resilience.GetCircuitState(Signals.Logs));
        Assert.False(Resilience.AllowAttempt(Signals.Logs));

        // First trip: OpenCount is 1, so the cooldown is 30 * 2^1 = 60s.
        _clock.Advance(TimeSpan.FromSeconds(59));
        Assert.Equal("open", Resilience.GetCircuitState(Signals.Logs));
        Assert.False(Resilience.AllowAttempt(Signals.Logs));
    }

    [Fact]
    public void AnElapsedCooldownGoesHalfOpenAndAdmitsExactlyOneProbe()
    {
        TripBreaker(Signals.Logs);
        _clock.Advance(TimeSpan.FromSeconds(61));

        Assert.Equal("half_open", Resilience.GetCircuitState(Signals.Logs));
        Assert.True(Resilience.AllowAttempt(Signals.Logs));
        // The probe is in flight: a second caller must not become a herd.
        Assert.Equal("half_open", Resilience.GetCircuitState(Signals.Logs));
        Assert.False(Resilience.AllowAttempt(Signals.Logs));
    }

    [Fact]
    public void ASuccessfulProbeClosesTheBreakerAndDecaysTheOpenCount()
    {
        TripBreaker(Signals.Logs);
        _clock.Advance(TimeSpan.FromSeconds(61));
        Assert.True(Resilience.AllowAttempt(Signals.Logs));

        Resilience.RecordSuccess(Signals.Logs);

        Assert.Equal("closed", Resilience.GetCircuitState(Signals.Logs));
        Assert.Equal(0, Resilience.GetCircuitOpenCount(Signals.Logs));
        Assert.True(Resilience.AllowAttempt(Signals.Logs));
    }

    [Fact]
    public void AFailedProbeRetripsWithALongerCooldown()
    {
        TripBreaker(Signals.Logs);
        _clock.Advance(TimeSpan.FromSeconds(61));
        Assert.True(Resilience.AllowAttempt(Signals.Logs));

        // Any probe failure re-trips — the exporter has not proved recovery.
        Resilience.RecordFailure(Signals.Logs, isTimeout: false);

        Assert.Equal("open", Resilience.GetCircuitState(Signals.Logs));
        Assert.Equal(2, Resilience.GetCircuitOpenCount(Signals.Logs));

        // Second trip: cooldown is 30 * 2^2 = 120s — 61 more seconds is not enough.
        _clock.Advance(TimeSpan.FromSeconds(61));
        Assert.Equal("open", Resilience.GetCircuitState(Signals.Logs));
        _clock.Advance(TimeSpan.FromSeconds(60));
        Assert.Equal("half_open", Resilience.GetCircuitState(Signals.Logs));
    }

    [Fact]
    public void TheExponentialCooldownClampsAtTheMaximum()
    {
        // Six trips: 30 * 2^6 = 1920s uncapped, clamped to 1024s.
        for (var trips = 0; trips < 6; trips++)
        {
            TripBreaker(Signals.Logs);
            _clock.Advance(TimeSpan.FromSeconds(Resilience.CircuitMaxCooldownSeconds + 1));
            Assert.True(Resilience.AllowAttempt(Signals.Logs));
            Resilience.RecordFailure(Signals.Logs, isTimeout: true);
        }
        Assert.True(Resilience.GetCircuitOpenCount(Signals.Logs) >= 6);

        _clock.Advance(TimeSpan.FromSeconds(Resilience.CircuitMaxCooldownSeconds - 1));
        Assert.Equal("open", Resilience.GetCircuitState(Signals.Logs));
        _clock.Advance(TimeSpan.FromSeconds(2));
        Assert.Equal("half_open", Resilience.GetCircuitState(Signals.Logs));
    }

    [Fact]
    public void TheCooldownBoundaryItselfIsHalfOpen()
    {
        TripBreaker(Signals.Logs);

        // Exactly the 60-second cooldown: zero remaining is "elapsed", not
        // "still cooling" — the boundary belongs to the half-open side.
        _clock.Advance(TimeSpan.FromSeconds(60));

        Assert.Equal("half_open", Resilience.GetCircuitState(Signals.Logs));
        Assert.True(Resilience.AllowAttempt(Signals.Logs));
    }

    [Fact]
    public void ASuccessfulProbeDecaysTheOpenCountByExactlyOne()
    {
        TripBreaker(Signals.Logs);
        _clock.Advance(TimeSpan.FromSeconds(61));
        Assert.True(Resilience.AllowAttempt(Signals.Logs));
        Resilience.RecordFailure(Signals.Logs, isTimeout: true);
        Assert.Equal(2, Resilience.GetCircuitOpenCount(Signals.Logs));
        _clock.Advance(TimeSpan.FromSeconds(121));
        Assert.True(Resilience.AllowAttempt(Signals.Logs));

        Resilience.RecordSuccess(Signals.Logs);

        // Decay, not reset: two accumulated trips leave one behind.
        Assert.Equal(1, Resilience.GetCircuitOpenCount(Signals.Logs));
    }

    [Fact]
    public void ANonTimeoutFailureRestartsTheTimeoutRunAtZero()
    {
        Resilience.RecordFailure(Signals.Logs, isTimeout: true);
        Resilience.RecordFailure(Signals.Logs, isTimeout: true);
        Resilience.RecordFailure(Signals.Logs, isTimeout: false);
        Resilience.RecordFailure(Signals.Logs, isTimeout: true);
        Resilience.RecordFailure(Signals.Logs, isTimeout: true);

        // Two timeouts after the reset are not three: still closed.
        Assert.Equal("closed", Resilience.GetCircuitState(Signals.Logs));

        Resilience.RecordFailure(Signals.Logs, isTimeout: true);
        Assert.Equal("open", Resilience.GetCircuitState(Signals.Logs));
    }

    [Fact]
    public void ResetRestoresTheSystemClock()
    {
        Resilience.Reset();
        Assert.Same(TimeProvider.System, Resilience.Clock);
    }
}
