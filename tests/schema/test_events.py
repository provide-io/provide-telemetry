# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import pytest

from undef.telemetry.schema.events import EventSchemaError, validate_event_name, validate_required_keys


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
