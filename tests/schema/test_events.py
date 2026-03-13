# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import pytest

from undef.telemetry.schema.events import (
    EventSchemaError,
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


def test_event_name_helper_returns_three_segment_name() -> None:
    assert event_name("auth", "login", "success") == "auth.login.success"


def test_event_name_helper_returns_four_segment_name() -> None:
    assert event_name("auth", "login", "password", "failed") == "auth.login.password.failed"


def test_event_name_helper_returns_five_segment_name() -> None:
    assert event_name("payment", "sub", "renewal", "attempt", "success") == "payment.sub.renewal.attempt.success"


def test_event_name_helper_rejects_two_segments() -> None:
    with pytest.raises(EventSchemaError, match=r"expected 3-5 segments, got 2"):
        event_name("auth", "login")


def test_event_name_helper_rejects_six_segments() -> None:
    with pytest.raises(EventSchemaError, match=r"expected 3-5 segments, got 6"):
        event_name("a", "b", "c", "d", "e", "f")


def test_event_name_helper_rejects_invalid_segment() -> None:
    with pytest.raises(EventSchemaError, match=r"invalid event segment: segment\[2\]=too-many"):
        event_name("auth", "login", "too-many")


@pytest.mark.parametrize(
    ("segments", "expected"),
    [
        (("too-many", "login", "success"), r"invalid event segment: segment\[0\]=too-many"),
        (("auth", "too-many", "success"), r"invalid event segment: segment\[1\]=too-many"),
        (("auth", "login", "ok", "BAD"), r"invalid event segment: segment\[3\]=BAD"),
    ],
)
def test_event_name_helper_reports_invalid_segment_label(segments: tuple[str, ...], expected: str) -> None:
    with pytest.raises(EventSchemaError, match=expected):
        event_name(*segments)
