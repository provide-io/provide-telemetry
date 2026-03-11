# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Event schema validation."""

from __future__ import annotations

import re

_EVENT_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_SEGMENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class EventSchemaError(ValueError):
    """Raised when an event violates schema policy."""


def event_name(domain: str, action: str, status: str) -> str:
    """Build a strict event name from validated segments."""
    for label, value in (("domain", domain), ("action", action), ("status", status)):
        if not _SEGMENT_RE.match(value):
            raise EventSchemaError(f"invalid event segment: {label}={value}")
    return f"{domain}.{action}.{status}"


def validate_event_name(name: str, strict_event_name: bool) -> None:
    if not strict_event_name:
        return
    if not _EVENT_RE.match(name):
        raise EventSchemaError(f"invalid event name: {name}")


def validate_required_keys(data: dict[str, object], required_keys: tuple[str, ...]) -> None:
    missing = [key for key in required_keys if key not in data]
    if missing:
        raise EventSchemaError(f"missing required keys: {', '.join(sorted(missing))}")
