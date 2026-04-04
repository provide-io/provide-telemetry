# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from provide.telemetry.schema.events import (
    Event,
    EventSchemaError,
    event,
    event_name,
    validate_event_name,
    validate_required_keys,
)


def test_validate_event_name_strict() -> None:
    validate_event_name("auth.login.success", strict_event_name=True)
    with pytest.raises(EventSchemaError, match=r"invalid event name: bad event"):
        validate_event_name("bad event", strict_event_name=True)


def test_validate_event_name_strict_accepts_four_segments() -> None:
    validate_event_name("auth.login.password.success", strict_event_name=True)


def test_validate_event_name_strict_accepts_five_segments() -> None:
    validate_event_name("payment.sub.renewal.attempt.success", strict_event_name=True)


def test_validate_event_name_strict_rejects_six_segments() -> None:
    with pytest.raises(EventSchemaError, match=r"invalid event name"):
        validate_event_name("a.b.c.d.e.f", strict_event_name=True)


def test_validate_event_name_strict_rejects_two_segments() -> None:
    with pytest.raises(EventSchemaError, match=r"invalid event name"):
        validate_event_name("a.b", strict_event_name=True)


def test_validate_event_name_relaxed() -> None:
    validate_event_name("bad event", strict_event_name=False)


def test_validate_required_keys() -> None:
    validate_required_keys({"a": 1, "b": 2}, ("a",))
    with pytest.raises(EventSchemaError, match=r"missing required keys: b"):
        validate_required_keys({"a": 1}, ("a", "b"))


def test_validate_required_keys_error_message_uses_comma_separator() -> None:
    with pytest.raises(EventSchemaError, match=r"missing required keys: a, b"):
        validate_required_keys({}, ("b", "a"))


# ── event_name() strict mode ────────────────────────────────────────


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
    ("segments", "expected"),
    [
        (("too-many", "login", "success"), r"invalid event segment: segment\[0\]=too-many"),
        (("auth", "too-many", "success"), r"invalid event segment: segment\[1\]=too-many"),
        (("auth", "login", "ok", "BAD"), r"invalid event segment: segment\[3\]=BAD"),
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


# ── event() / Event class ─────────────────────────────────────────


def test_event_three_segments_das() -> None:
    """event(domain, action, status) returns Event with correct fields."""
    e = event("auth", "login", "success")
    assert isinstance(e, Event)
    assert isinstance(e, str)
    assert str(e) == "auth.login.success"
    assert e.domain == "auth"
    assert e.action == "login"
    assert e.resource is None
    assert e.status == "success"


def test_event_four_segments_dars() -> None:
    """event(domain, action, resource, status) returns Event with resource."""
    e = event("db", "query", "orders", "failure")
    assert isinstance(e, Event)
    assert str(e) == "db.query.orders.failure"
    assert e.domain == "db"
    assert e.action == "query"
    assert e.resource == "orders"
    assert e.status == "failure"


def test_event_string_equality() -> None:
    """str(event(...)) produces the dot-joined name."""
    assert str(event("a", "b", "c")) == "a.b.c"


def test_event_too_few_segments_raises() -> None:
    """event() with fewer than 3 segments raises EventSchemaError."""
    with pytest.raises(EventSchemaError, match=r"event\(\) requires 3 or 4 segments"):
        event("a", "b")


def test_event_single_segment_raises() -> None:
    """event() with 1 segment raises EventSchemaError."""
    with pytest.raises(EventSchemaError, match=r"event\(\) requires 3 or 4 segments"):
        event("a")


def test_event_zero_segments_raises() -> None:
    """event() with no segments raises EventSchemaError."""
    with pytest.raises(EventSchemaError, match=r"event\(\) requires 3 or 4 segments"):
        event()


def test_event_too_many_segments_raises() -> None:
    """event() with more than 4 segments raises EventSchemaError."""
    with pytest.raises(EventSchemaError, match=r"event\(\) requires 3 or 4 segments"):
        event("a", "b", "c", "d", "e")


def test_event_strict_mode_validates_segments() -> None:
    """In strict mode, event() validates segment format."""
    with _strict_config(), pytest.raises(EventSchemaError, match=r"invalid event segment"):
        event("auth", "login", "BAD-SEGMENT")


def test_event_strict_mode_accepts_valid_segments() -> None:
    """In strict mode, event() accepts valid lowercase segments."""
    with _strict_config():
        e = event("auth", "login", "success")
        assert str(e) == "auth.login.success"


def test_event_strict_mode_four_segments() -> None:
    """In strict mode, event() validates 4 valid segments."""
    with _strict_config():
        e = event("db", "query", "orders", "success")
        assert e.resource == "orders"


def test_event_as_dict_three_segments() -> None:
    """as_dict() returns dict with event, domain, action, status."""
    e = event("auth", "login", "success")
    d = e.as_dict()
    assert d == {
        "event": "auth.login.success",
        "domain": "auth",
        "action": "login",
        "status": "success",
    }
    assert "resource" not in d


def test_event_as_dict_four_segments() -> None:
    """as_dict() includes resource when 4 segments."""
    e = event("db", "query", "orders", "failure")
    d = e.as_dict()
    assert d == {
        "event": "db.query.orders.failure",
        "domain": "db",
        "action": "query",
        "resource": "orders",
        "status": "failure",
    }


def test_event_is_string_subclass() -> None:
    """Event can be used anywhere a string is expected."""
    e = event("auth", "login", "success")
    assert e == "auth.login.success"
    assert e.startswith("auth")
    assert "login" in e


def test_event_name_still_works_as_deprecated_alias() -> None:
    """event_name() continues to work and returns a plain str."""
    with _relaxed_config():
        result = event_name("auth", "login", "success")
        assert result == "auth.login.success"
        assert type(result) is str
        assert not isinstance(result, Event)


# ── inject_das_fields processor ────────────────────────────────────


def test_inject_das_fields_extracts_from_event_three_segments() -> None:
    """inject_das_fields populates domain/action/status from Event."""
    from provide.telemetry.logger.processors import inject_das_fields

    e = event("auth", "login", "success")
    event_dict: dict[str, object] = {"event": e, "user_id": "123"}
    result = inject_das_fields(None, "info", event_dict)
    assert result["domain"] == "auth"
    assert result["action"] == "login"
    assert result["status"] == "success"
    assert "resource" not in result
    assert result["event"] == "auth.login.success"
    assert type(result["event"]) is str


def test_inject_das_fields_extracts_from_event_four_segments() -> None:
    """inject_das_fields populates resource from 4-segment Event."""
    from provide.telemetry.logger.processors import inject_das_fields

    e = event("db", "query", "orders", "failure")
    event_dict: dict[str, object] = {"event": e}
    result = inject_das_fields(None, "info", event_dict)
    assert result["domain"] == "db"
    assert result["action"] == "query"
    assert result["resource"] == "orders"
    assert result["status"] == "failure"
    assert result["event"] == "db.query.orders.failure"


def test_inject_das_fields_ignores_plain_string_event() -> None:
    """inject_das_fields is a no-op when event is a plain string."""
    from provide.telemetry.logger.processors import inject_das_fields

    event_dict: dict[str, object] = {"event": "plain.string.event"}
    result = inject_das_fields(None, "info", event_dict)
    assert result["event"] == "plain.string.event"
    assert "domain" not in result
    assert "action" not in result
    assert "status" not in result


def test_inject_das_fields_ignores_missing_event() -> None:
    """inject_das_fields is a no-op when event key is absent."""
    from provide.telemetry.logger.processors import inject_das_fields

    event_dict: dict[str, object] = {"some_key": "value"}
    result = inject_das_fields(None, "info", event_dict)
    assert "domain" not in result
