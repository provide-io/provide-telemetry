# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Mutation-killing tests for harden_input priority-key truncation logic.

The priority logic (added after the initial harden_input implementation)
preserves structlog/telemetry control fields (event, level, trace_id, etc.)
when max_attr_count would otherwise silently drop them.  These tests cover
mutations in the four new lines:

    priority   = {k: event_dict[k] for k in _HARDEN_PRIORITY_KEYS if k in event_dict}
    remaining  = max(0, max_attr_count - len(priority))
    user_keys  = [k for k in event_dict if k not in _HARDEN_PRIORITY_KEYS]
    event_dict = {**priority, **{k: event_dict[k] for k in user_keys[:remaining]}}
"""

from __future__ import annotations

from provide.telemetry.logger.processors import _HARDEN_PRIORITY_KEYS, harden_input


class TestHardenInputPriorityTruncation:
    """Priority keys must survive truncation; user-key budget is max - len(priority)."""

    def test_priority_keys_preserved_when_slots_exhausted(self) -> None:
        """Kills: `max_attr_count - len(priority)` → `+ len(priority)`.

        When all max_attr_count slots are claimed by priority keys, no user keys
        should appear.  The `+` mutation inflates remaining, letting user keys in.
        """
        proc = harden_input(max_value_length=100, max_attr_count=2, max_depth=5)
        event_dict = {
            "event": "login",
            "level": "info",
            "user": "alice",
            "extra": "data",
        }
        result = proc(None, "", event_dict)
        assert result.get("event") == "login", "priority key 'event' must be preserved"
        assert result.get("level") == "info", "priority key 'level' must be preserved"
        assert "user" not in result, "user key must be absent when priority fills all slots"
        assert "extra" not in result, "user key must be absent when priority fills all slots"
        assert len(result) == 2

    def test_remaining_slots_after_priority_filled_by_user_keys(self) -> None:
        """Kills: `max(0, max_attr_count - len(priority))` → `max(1, ...)`.

        With max=3 and two priority keys, remaining=max(0,1)=1.  The `max(1,…)`
        mutation gives the same answer here (max(1,1)=1), but when priority fills
        all slots: max(0,0)=0 vs max(1,0)=1 — the mutation lets an extra user key
        through, caught by test_priority_keys_preserved_when_slots_exhausted above.

        This companion test verifies the *positive* case: exactly one user key
        fills the single remaining slot.
        """
        proc = harden_input(max_value_length=100, max_attr_count=3, max_depth=5)
        event_dict = {
            "event": "login",
            "level": "info",
            "user": "alice",
            "request_id": "req-1",
        }
        result = proc(None, "", event_dict)
        assert result.get("event") == "login"
        assert result.get("level") == "info"
        assert len(result) == 3, "priority(2) + remaining(1) = 3 keys total"
        user_present = sum(1 for k in ("user", "request_id") if k in result)
        assert user_present == 1, "exactly one user key should fill the remaining slot"

    def test_user_keys_exclude_priority_keys(self) -> None:
        """Kills: `k not in _HARDEN_PRIORITY_KEYS` → `k in _HARDEN_PRIORITY_KEYS`.

        The user_keys list must contain only non-priority keys.  If the condition
        flips, user_keys would be the priority keys and the non-priority values
        would be dropped instead of included.
        """
        proc = harden_input(max_value_length=100, max_attr_count=3, max_depth=5)
        event_dict = {
            "event": "login",
            "level": "info",
            "user": "alice",
            "extra": "data",
        }
        result = proc(None, "", event_dict)
        # With correct logic: priority={event,level}, remaining=1, user_keys=[user,extra]
        # → result includes event, level, and one of {user, extra}
        assert "user" in result or "extra" in result, "at least one non-priority key must be in user_keys"
        assert result.get("event") == "login"
        assert result.get("level") == "info"

    def test_initial_depth_zero_for_value_cleaning(self) -> None:
        """Kills: `_clean_value(v, 0)` → `_clean_value(v, 1)` (mutmut_24).

        Values are cleaned starting at depth 0.  Starting at depth 1 means that
        with max_depth=1 no nested dict/list recursion occurs (1 < 1 is False),
        so control characters inside nested dicts survive unchanged.
        """
        proc = harden_input(max_value_length=100, max_attr_count=0, max_depth=1)
        event_dict: dict[str, object] = {
            "event": "x",
            "nested": {"inner": "\x01dirty"},
        }
        result = proc(None, "", event_dict)
        # With depth=0 (correct): nested dict IS recursed → inner value cleaned
        assert result["nested"] == {"inner": "dirty"}, (
            "nested dict must be recursed when starting at depth 0 with max_depth=1"
        )

    def test_all_priority_keys_recognised(self) -> None:
        """_HARDEN_PRIORITY_KEYS must contain the seven canonical control fields."""
        expected = {"event", "level", "timestamp", "trace_id", "span_id", "logger", "logger_name"}
        assert expected <= _HARDEN_PRIORITY_KEYS, f"missing priority keys: {expected - _HARDEN_PRIORITY_KEYS}"
