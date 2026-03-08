# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 MindTenet LLC
# This file is part of Undef Telemetry.
"""Event schema validation."""

from __future__ import annotations

import re

_EVENT_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


class EventSchemaError(ValueError):
    """Raised when an event violates schema policy."""


def validate_event_name(name: str, strict_event_name: bool) -> None:
    if not strict_event_name:
        return
    if not _EVENT_RE.match(name):
        raise EventSchemaError(f"invalid event name: {name}")


def validate_required_keys(data: dict[str, object], required_keys: tuple[str, ...]) -> None:
    missing = [key for key in required_keys if key not in data]
    if missing:
        raise EventSchemaError(f"missing required keys: {', '.join(sorted(missing))}")
