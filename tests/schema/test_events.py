# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import pytest

from provide.telemetry.schema.events import (
    EventSchemaError,
    event_name,
    validate_event_name,
    validate_required_keys,
)


def test_validate_event_name_strict() -> None:
    validate_event_name("auth.login.success", strict_event_name=True)
    with pytest.raises(EventSchemaError, match=r"invalid event name: bad event"):
        validate_event_name("bad event", strict_event_name=True)


def test_validate_event_name_relaxed() -> None:
    validate_event_name("bad event", strict_event_name=False)


def test_validate_required_keys() -> None:
    validate_required_keys({"a": 1, "b": 2}, ("a",))
    with pytest.raises(EventSchemaError, match=r"missing required keys: b"):
        validate_required_keys({"a": 1}, ("a", "b"))


def test_validate_required_keys_error_message_uses_comma_separator() -> None:
    with pytest.raises(EventSchemaError, match=r"missing required keys: a, b"):
        validate_required_keys({}, ("b", "a"))


def test_event_name_helper_returns_three_segment_name() -> None:
    assert event_name("auth", "login", "success") == "auth.login.success"


@contextmanager
def _strict_config() -> Iterator[None]:
    """Patch runtime to report strict event-name mode."""
    with patch("provide.telemetry.runtime._is_strict_event_name", return_value=True):
        yield


@contextmanager
def _relaxed_config() -> Iterator[None]:
    """Patch runtime to report relaxed event-name mode (default)."""
    with patch("provide.telemetry.runtime._is_strict_event_name", return_value=False):
        yield


def test_event_name_strict_returns_three_segment_name() -> None:
    with _strict_config():
        assert event_name("auth", "login", "success") == "auth.login.success"


def test_event_name_strict_returns_four_segment_name() -> None:
    with _strict_config():
        assert event_name("auth", "login", "password", "failed") == "auth.login.password.failed"


def test_event_name_strict_returns_five_segment_name() -> None:
    with _strict_config():
        assert event_name("payment", "sub", "renewal", "attempt", "success") == "payment.sub.renewal.attempt.success"


def test_event_name_strict_rejects_two_segments() -> None:
    with _strict_config(), pytest.raises(EventSchemaError, match=r"expected 3-5 segments, got 2"):
        event_name("auth", "login")


def test_event_name_strict_rejects_six_segments() -> None:
    with _strict_config(), pytest.raises(EventSchemaError, match=r"expected 3-5 segments, got 6"):
        event_name("a", "b", "c", "d", "e", "f")


def test_event_name_strict_rejects_invalid_segment() -> None:
    with _strict_config(), pytest.raises(EventSchemaError, match=r"invalid event segment: segment\[2\]=too-many"):
        event_name("auth", "login", "too-many")


@pytest.mark.parametrize(
    ("domain", "action", "status", "expected"),
    [
        ("too-many", "login", "success", r"invalid event segment: domain=too-many"),
        ("auth", "too-many", "success", r"invalid event segment: action=too-many"),
    ],
)
def test_event_name_strict_reports_invalid_segment_label(segments: tuple[str, ...], expected: str) -> None:
    with _strict_config(), pytest.raises(EventSchemaError, match=expected):
        event_name(*segments)


# ── event_name() relaxed mode (default) ─────────────────────────────


def test_event_name_relaxed_accepts_single_segment() -> None:
    with _relaxed_config():
        assert event_name("sysop_cors_disabled") == "sysop_cors_disabled"


def test_event_name_relaxed_accepts_two_segments() -> None:
    with _relaxed_config():
        assert event_name("auth", "login") == "auth.login"


def test_event_name_relaxed_accepts_arbitrary_format() -> None:
    with _relaxed_config():
        assert event_name("My-Event", "Name") == "My-Event.Name"


def test_event_name_relaxed_still_requires_at_least_one_segment() -> None:
    with _relaxed_config(), pytest.raises(EventSchemaError, match=r"^event_name requires at least 1 segment$"):
        event_name()


def test_event_name_relaxed_accepts_three_segments() -> None:
    with _relaxed_config():
        assert event_name("auth", "login", "success") == "auth.login.success"


def test_event_name_strict_rejects_zero_segments() -> None:
    with _strict_config(), pytest.raises(EventSchemaError, match=r"expected 3-5 segments, got 0"):
        event_name()


# ── event_name() with real runtime config ────────────────────────────


def test_event_name_defaults_to_relaxed_without_active_config() -> None:
    """When no config has been applied, _is_strict_event_name returns False (relaxed)."""
    from provide.telemetry.runtime import reset_runtime_for_tests

    reset_runtime_for_tests()
    # With no active config, single-segment names should work (relaxed mode)
    assert event_name("single_segment") == "single_segment"


def test_event_name_uses_real_runtime_config_relaxed() -> None:
    """Exercises _is_strict_event_name with a real active config (non-strict)."""
    from provide.telemetry.config import TelemetryConfig
    from provide.telemetry.runtime import apply_runtime_config, reset_runtime_for_tests

    try:
        apply_runtime_config(TelemetryConfig(strict_schema=False))
        assert event_name("single_segment") == "single_segment"
    finally:
        reset_runtime_for_tests()


def test_event_name_uses_real_runtime_config_strict() -> None:
    """Exercises _is_strict_event_name with a real active config (strict)."""
    from provide.telemetry.config import TelemetryConfig
    from provide.telemetry.runtime import apply_runtime_config, reset_runtime_for_tests

    try:
        apply_runtime_config(TelemetryConfig(strict_schema=True))
        with pytest.raises(EventSchemaError, match=r"expected 3-5 segments"):
            event_name("single_segment")
    finally:
        reset_runtime_for_tests()
