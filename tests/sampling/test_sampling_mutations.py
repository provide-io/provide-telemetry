# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests targeting mutation-testing survivors in sampling.py."""

from __future__ import annotations

import pytest

from undef.telemetry import health as health_mod
from undef.telemetry import sampling as sampling_mod
from undef.telemetry.sampling import (
    SamplingPolicy,
    _normalize_rate,
    get_sampling_policy,
    reset_sampling_for_tests,
    set_sampling_policy,
    should_sample,
)


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    health_mod.reset_health_for_tests()
    sampling_mod.reset_sampling_for_tests()


# ---------------------------------------------------------------------------
# _normalize_rate survivors
# ---------------------------------------------------------------------------


class TestNormalizeRate:
    """Kill mutants in _normalize_rate."""

    def test_clamps_above_one_to_exactly_one(self) -> None:
        """Kills `min(1.0, rate)` -> `min(2.0, rate)` mutant.

        A rate of 1.5 must be clamped to exactly 1.0, not 1.5.
        """
        assert _normalize_rate(1.5) == 1.0

    def test_clamps_below_zero_to_exactly_zero(self) -> None:
        """Kills `max(0.0, ...)` mutations."""
        assert _normalize_rate(-0.5) == 0.0

    def test_one_point_zero_passes_through(self) -> None:
        """1.0 is a valid rate and should not be modified."""
        assert _normalize_rate(1.0) == 1.0

    def test_zero_passes_through(self) -> None:
        """0.0 is a valid rate."""
        assert _normalize_rate(0.0) == 0.0

    def test_mid_value_passes_through(self) -> None:
        """Value between 0 and 1 should pass through unchanged."""
        assert _normalize_rate(0.5) == 0.5

    def test_value_just_above_one(self) -> None:
        """1.0001 should be clamped to 1.0, not 1.0001."""
        assert _normalize_rate(1.0001) == 1.0


# ---------------------------------------------------------------------------
# set/get_sampling_policy survivors
# ---------------------------------------------------------------------------


class TestSamplingPolicy:
    """Kill mutants in set/get_sampling_policy."""

    def test_unknown_signal_falls_back_to_logs(self) -> None:
        """Kills fallback `"logs"` -> `"LOGS"`, `"XXlogsXX"` mutants.

        Unknown signal should store/retrieve from "logs" bucket.
        """
        policy = SamplingPolicy(default_rate=0.42)
        set_sampling_policy("unknown_signal", policy)
        # Should be stored under "logs"
        result = get_sampling_policy("logs")
        assert result.default_rate == 0.42

    def test_unknown_signal_get_falls_back_to_logs(self) -> None:
        """Get with unknown signal returns logs policy."""
        set_sampling_policy("logs", SamplingPolicy(default_rate=0.33))
        result = get_sampling_policy("nonexistent")
        assert result.default_rate == 0.33

    def test_known_signals_are_distinct(self) -> None:
        """Each known signal has its own bucket."""
        set_sampling_policy("logs", SamplingPolicy(default_rate=0.1))
        set_sampling_policy("traces", SamplingPolicy(default_rate=0.2))
        set_sampling_policy("metrics", SamplingPolicy(default_rate=0.3))
        assert get_sampling_policy("logs").default_rate == 0.1
        assert get_sampling_policy("traces").default_rate == 0.2
        assert get_sampling_policy("metrics").default_rate == 0.3

    def test_not_in_vs_in_mutant(self) -> None:
        """Kills `not in` -> `in` mutant in fallback check.

        A known signal like "traces" must NOT fall back to "logs".
        """
        set_sampling_policy("traces", SamplingPolicy(default_rate=0.77))
        set_sampling_policy("logs", SamplingPolicy(default_rate=0.11))
        # "traces" must return 0.77, not fall back to logs (0.11)
        assert get_sampling_policy("traces").default_rate == 0.77

    def test_overrides_are_normalized(self) -> None:
        """Override rates are also clamped to [0, 1]."""
        policy = SamplingPolicy(default_rate=0.5, overrides={"evt": 2.0, "low": -0.5})
        set_sampling_policy("logs", policy)
        result = get_sampling_policy("logs")
        assert result.overrides["evt"] == 1.0
        assert result.overrides["low"] == 0.0


# ---------------------------------------------------------------------------
# should_sample survivors
# ---------------------------------------------------------------------------


class TestShouldSample:
    """Kill mutants in should_sample."""

    def test_key_override_used_when_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills `get_sampling_policy(signal)` -> `get_sampling_policy(None)` and
        `key is not None and` -> `is None and` mutants.

        When key matches an override, that rate should be used, not the default.
        """
        set_sampling_policy("logs", SamplingPolicy(default_rate=0.0, overrides={"special": 1.0}))
        monkeypatch.setattr("random.random", lambda: 0.5)
        # Default rate is 0.0, but override for "special" is 1.0
        assert should_sample("logs", key="special") is True
        # Without key, default rate of 0.0 means no sampling
        assert should_sample("logs") is False

    def test_dropped_counter_incremented_with_correct_signal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills `increment_dropped(signal)` -> `increment_dropped(None)` mutant."""
        set_sampling_policy("traces", SamplingPolicy(default_rate=0.0))
        monkeypatch.setattr("random.random", lambda: 0.5)
        should_sample("traces")
        snap = health_mod.get_health_snapshot()
        assert snap.dropped_traces == 1
        assert snap.dropped_logs == 0  # Must be traces, not logs

    def test_dropped_counter_not_incremented_on_keep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills `not keep` -> `keep` mutant."""
        set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))
        monkeypatch.setattr("random.random", lambda: 0.0)
        result = should_sample("logs")
        assert result is True
        snap = health_mod.get_health_snapshot()
        assert snap.dropped_logs == 0

    def test_boundary_sample_rate_equality(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills `<=` -> `<` mutant.

        When random() returns exactly the rate, should_sample must return True.
        """
        set_sampling_policy("logs", SamplingPolicy(default_rate=0.5))
        monkeypatch.setattr("random.random", lambda: 0.5)
        assert should_sample("logs") is True

    def test_just_above_rate_is_dropped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When random() > rate, sample is dropped."""
        set_sampling_policy("logs", SamplingPolicy(default_rate=0.5))
        monkeypatch.setattr("random.random", lambda: 0.50001)
        assert should_sample("logs") is False

    def test_signal_passed_to_get_policy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills `get_sampling_policy(signal)` -> `get_sampling_policy(None)`.

        Set different policies for different signals and verify correct one is used.
        """
        set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))
        set_sampling_policy("traces", SamplingPolicy(default_rate=0.0))
        monkeypatch.setattr("random.random", lambda: 0.5)
        assert should_sample("logs") is True
        assert should_sample("traces") is False


# ---------------------------------------------------------------------------
# reset_sampling_for_tests survivors
# ---------------------------------------------------------------------------


class TestResetSamplingForTests:
    """Kill mutants in reset_sampling_for_tests."""

    def test_resets_all_three_signals(self) -> None:
        """Kills string literal mutations in signal names ("logs", "traces", "metrics")."""
        set_sampling_policy("logs", SamplingPolicy(default_rate=0.1))
        set_sampling_policy("traces", SamplingPolicy(default_rate=0.2))
        set_sampling_policy("metrics", SamplingPolicy(default_rate=0.3))

        reset_sampling_for_tests()

        assert get_sampling_policy("logs").default_rate == 1.0
        assert get_sampling_policy("traces").default_rate == 1.0
        assert get_sampling_policy("metrics").default_rate == 1.0

    def test_resets_overrides_too(self) -> None:
        """After reset, overrides should be empty."""
        set_sampling_policy("logs", SamplingPolicy(default_rate=0.5, overrides={"evt": 0.1}))
        reset_sampling_for_tests()
        assert get_sampling_policy("logs").overrides == {}
