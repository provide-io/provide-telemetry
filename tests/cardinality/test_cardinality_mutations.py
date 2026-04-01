# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests targeting surviving mutation-testing mutants in cardinality.py."""

from __future__ import annotations

import pytest

from provide.telemetry import cardinality as cardinality_mod
from provide.telemetry.cardinality import (
    OVERFLOW_VALUE,
    _prune_expired,
    clear_cardinality_limits,
    guard_attributes,
    register_cardinality_limit,
)


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    clear_cardinality_limits()


# ── _prune_expired: or→and mutation ──────────────────────────────────


class TestPruneExpiredOrVsAnd:
    def test_prune_with_limit_but_no_seen_returns_early(self) -> None:
        """Kills: `limit is None or seen is None` → `and`.
        If only _limits has the key but _seen does not, should return early (no crash).
        """
        cardinality_mod._limits["orphan"] = cardinality_mod.CardinalityLimit(max_values=5)
        # Do NOT add to _seen → _seen.get("orphan") is None
        _prune_expired("orphan", 9999.0)  # should not raise

    def test_prune_with_seen_but_no_limit_returns_early(self) -> None:
        """If _seen has the key but _limits does not, also returns early."""
        cardinality_mod._seen["orphan2"] = {"val": 1.0}
        _prune_expired("orphan2", 9999.0)  # should not raise

    def test_prune_with_neither_returns_early(self) -> None:
        _prune_expired("nonexistent", 9999.0)


# ── _prune_expired: seen_at < threshold (< vs <=) ───────────────────


class TestPruneThresholdBoundary:
    def test_exact_threshold_not_pruned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: `seen_at < threshold` → `<=`.
        An entry at exactly the threshold should NOT be pruned (< is strict)."""
        now = 1000.0
        monkeypatch.setattr("time.monotonic", lambda: now)
        register_cardinality_limit("k", max_values=10, ttl_seconds=100.0)
        # Insert a value at time 900.0 → threshold = 1000 - 100 = 900.0
        cardinality_mod._seen["k"]["val"] = 900.0
        _prune_expired("k", now)
        # With `<`, 900.0 < 900.0 is False → not pruned
        assert "val" in cardinality_mod._seen["k"]

    def test_just_before_threshold_is_pruned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        now = 1000.0
        monkeypatch.setattr("time.monotonic", lambda: now)
        register_cardinality_limit("k", max_values=10, ttl_seconds=100.0)
        cardinality_mod._seen["k"]["val"] = 899.9
        _prune_expired("k", now)
        assert "val" not in cardinality_mod._seen["k"]


# ── guard_attributes: continue→break ────────────────────────────────


class TestGuardAttributesContinueVsBreak:
    def test_multiple_keys_all_processed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: `continue` → `break` at various points.
        With multiple keys having limits, all should be processed, not just the first."""
        now = 1000.0
        monkeypatch.setattr("time.monotonic", lambda: now)
        register_cardinality_limit("key_a", max_values=1)
        register_cardinality_limit("key_b", max_values=1)

        # First call registers both values
        result1 = guard_attributes({"key_a": "a1", "key_b": "b1", "other": "x"})
        assert result1 == {"key_a": "a1", "key_b": "b1", "other": "x"}

        # Second call with different values should overflow both (max=1)
        result2 = guard_attributes({"key_a": "a2", "key_b": "b2", "other": "y"})
        assert result2["key_a"] == OVERFLOW_VALUE
        assert result2["key_b"] == OVERFLOW_VALUE
        assert result2["other"] == "y"  # unguarded key untouched

    def test_continue_after_seen_value_update_processes_next_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: `continue` -> `break` when updating a seen value.

        First call registers values for two guarded keys. Second call with
        same values should update timestamps (continue) and process both.
        The break mutant would stop after the first key.
        """
        now = 1000.0
        monkeypatch.setattr("time.monotonic", lambda: now)
        register_cardinality_limit("k1", max_values=2)
        register_cardinality_limit("k2", max_values=1)

        # First call: register values
        guard_attributes({"k1": "a", "k2": "x"})

        # Second call: same values → hit "value in seen" → continue path
        # Then add a NEW value for k2 which should overflow since max=1
        result = guard_attributes({"k1": "a", "k2": "y"})
        # k1="a" hits continue (already seen), k2="y" is new and overflows
        assert result["k1"] == "a"
        assert result["k2"] == OVERFLOW_VALUE

    def test_key_without_limit_continues_to_next(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A key with no limit should be skipped (continue), and the next key with a limit processed."""
        now = 1000.0
        monkeypatch.setattr("time.monotonic", lambda: now)
        register_cardinality_limit("guarded", max_values=1)
        # "unguarded" has no limit
        result = guard_attributes({"unguarded": "u1", "guarded": "g1"})
        assert result["unguarded"] == "u1"
        assert result["guarded"] == "g1"

        # Now overflow guarded
        result2 = guard_attributes({"unguarded": "u2", "guarded": "g2"})
        assert result2["unguarded"] == "u2"
        assert result2["guarded"] == OVERFLOW_VALUE


# ── guard_attributes: setdefault(key, {}) → setdefault(key, None) ───


class TestGuardSetdefault:
    def test_setdefault_creates_dict_not_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: `setdefault(key, {})` → `setdefault(key, None)`."""
        now = 1000.0
        monkeypatch.setattr("time.monotonic", lambda: now)
        register_cardinality_limit("new_key", max_values=5)
        # Remove from _seen to force setdefault path in guard_attributes
        cardinality_mod._seen.pop("new_key", None)
        # This should work — if setdefault returned None, the `value in seen` check would crash
        result = guard_attributes({"new_key": "v1"})
        assert result["new_key"] == "v1"


# ── register_cardinality_limit: ttl_seconds default & max ───────────


class TestRegisterCardinalityLimit:
    def test_default_ttl_is_300(self) -> None:
        """Kills: `ttl_seconds=300.0` → `301.0`."""
        register_cardinality_limit("test_key", max_values=10)
        limits = cardinality_mod.get_cardinality_limits()
        assert limits["test_key"].ttl_seconds == 300.0

    def test_ttl_clamped_to_min_1(self) -> None:
        """Kills: `max(1.0, ttl_seconds)` → `max(2.0, ...)`."""
        register_cardinality_limit("clamped", max_values=10, ttl_seconds=0.5)
        limits = cardinality_mod.get_cardinality_limits()
        assert limits["clamped"].ttl_seconds == 1.0

        # 1.5 should remain 1.5 (not clamped to 2.0)
        register_cardinality_limit("unclamped", max_values=10, ttl_seconds=1.5)
        assert cardinality_mod.get_cardinality_limits()["unclamped"].ttl_seconds == 1.5

    def test_seen_setdefault_uses_correct_key(self) -> None:
        """Kills: `_seen.setdefault(key, {})` → `setdefault(None, {})`."""
        register_cardinality_limit("real_key", max_values=5)
        assert "real_key" in cardinality_mod._seen
        assert None not in cardinality_mod._seen
