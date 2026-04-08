# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Event schema validation."""

from __future__ import annotations

__all__ = [
    "Event",
    "EventSchemaError",
    "event",
    "event_name",
    "validate_event_name",
    "validate_required_keys",
]

import re
import types

from provide.telemetry.exceptions import TelemetryError

_SEG = r"[a-z][a-z0-9_]*"
_EVENT_RE = re.compile(rf"^{_SEG}(?:\.{_SEG}){{2,4}}$")
_SEGMENT_RE = re.compile(rf"^{_SEG}$")
_MIN_SEGMENTS = 3
_MAX_SEGMENTS = 5

# Cached module reference to avoid per-call deferred import overhead.
# We cache the module (not the function) so that unittest.mock.patch
# on the function attribute still works.
_runtime_mod: types.ModuleType | None = None


def _get_strict_check() -> bool:
    """Return strict-event-name flag, caching the module import on first call."""
    global _runtime_mod
    if _runtime_mod is None:  # pragma: no mutate — caching optimization, not behavioral
        from provide.telemetry import runtime

        _runtime_mod = runtime  # pragma: no mutate
    return _runtime_mod._is_strict_event_name()  # type: ignore[no-any-return]


class EventSchemaError(TelemetryError, ValueError):
    """Raised when an event violates schema policy."""


class Event(str):
    """String subclass carrying DA(R)S metadata.

    Behaves as a plain string (the dot-joined event name) but also
    exposes ``.domain``, ``.action``, ``.resource``, ``.status`` attributes.
    """

    domain: str
    action: str
    resource: str | None
    status: str

    def __new__(cls, *segments: str) -> Event:
        """Create an Event from 3 (DAS) or 4 (DARS) segments."""
        if len(segments) not in (3, 4):
            raise EventSchemaError(f"event() requires 3 or 4 segments (DA[R]S), got {len(segments)}")

        if _get_strict_check():
            for i, seg in enumerate(segments):
                if not _SEGMENT_RE.match(seg):
                    raise EventSchemaError(f"invalid event segment: segment[{i}]={seg}")

        name = ".".join(segments)
        instance = super().__new__(cls, name)

        if len(segments) == 3:
            instance.domain = segments[0]
            instance.action = segments[1]
            instance.resource = None
            instance.status = segments[2]
        else:
            instance.domain = segments[0]
            instance.action = segments[1]
            instance.resource = segments[2]
            instance.status = segments[3]

        return instance

    def as_dict(self) -> dict[str, str]:
        """Return a dictionary with the event name and DA(R)S fields."""
        d: dict[str, str] = {
            "event": str(self),
            "domain": self.domain,
            "action": self.action,
            "status": self.status,
        }
        if self.resource is not None:
            d["resource"] = self.resource
        return d


def event(*segments: str) -> Event:
    """Create a structured event with DA(R)S fields.

    3 args: ``event(domain, action, status)`` -- DAS
    4 args: ``event(domain, action, resource, status)`` -- DARS
    """
    return Event(*segments)


def event_name(*segments: str) -> str:
    """Build a dot-joined event name string from segments.

    In strict mode (``strict_schema`` or ``strict_event_name``): enforces 3-5
    lowercase/underscore segments.  In relaxed mode (default): accepts 1+
    segments with no format validation.
    """
    strict = _get_strict_check()
    if strict:
        if not (_MIN_SEGMENTS <= len(segments) <= _MAX_SEGMENTS):
            raise EventSchemaError(f"expected {_MIN_SEGMENTS}-{_MAX_SEGMENTS} segments, got {len(segments)}")
        for i, value in enumerate(segments):
            if not _SEGMENT_RE.match(value):
                raise EventSchemaError(f"invalid event segment: segment[{i}]={value}")
    elif len(segments) == 0:
        raise EventSchemaError("event_name requires at least 1 segment")
    return ".".join(segments)


def validate_event_name(name: str, strict_event_name: bool) -> None:
    if not strict_event_name:
        return
    if not _EVENT_RE.match(name):
        raise EventSchemaError(f"invalid event name: {name}")


def validate_required_keys(data: dict[str, object], required_keys: tuple[str, ...]) -> None:
    missing = [key for key in required_keys if key not in data]
    if missing:
        raise EventSchemaError(f"missing required keys: {', '.join(sorted(missing))}")
