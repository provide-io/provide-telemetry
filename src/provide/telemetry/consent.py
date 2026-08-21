# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Consent-aware telemetry collection."""

from __future__ import annotations

__all__ = [
    "ConsentLevel",
    "get_consent_level",
    "set_consent_level",
    "should_allow",
]

import contextlib
import enum
import os
import threading

from provide.telemetry.levels import LogSeverity, level_order


class ConsentLevel(enum.Enum):
    FULL = "FULL"
    FUNCTIONAL = "FUNCTIONAL"
    MINIMAL = "MINIMAL"
    NONE = "NONE"


_lock = threading.Lock()
_level: ConsentLevel = ConsentLevel.FULL


def set_consent_level(level: ConsentLevel) -> None:
    global _level
    with _lock:
        _level = level


def get_consent_level() -> ConsentLevel:
    with _lock:
        return _level


def _rank(log_level: str | None) -> int:
    """Order a log level for consent comparisons.

    Resolves through the one shared table. An unrecognised level now ranks INFO
    rather than the old local default of 0/TRACE; both sit below the WARN and
    ERROR gates below, so no consent decision changes. FATAL does change: it
    used to be unrecognised and was dropped as if it were the least severe
    record in the ladder.

    The two hoisted pragma constants this replaced -- a placeholder for the
    missing-level lookup and its 0 rank -- went with the dict they served.
    """
    return level_order(log_level)


def should_allow(signal: str, log_level: str | None = None) -> bool:
    with _lock:
        level = _level

    if level == ConsentLevel.FULL:
        return True
    if level == ConsentLevel.NONE:
        return False
    if level == ConsentLevel.FUNCTIONAL:
        if signal == "logs":
            return _rank(log_level) >= LogSeverity.WARN
        return signal != "context"  # traces and metrics allowed; context blocked
    # MINIMAL
    if signal == "logs":
        return _rank(log_level) >= LogSeverity.ERROR
    return False  # traces/metrics/context blocked at MINIMAL


def _load_consent_from_env() -> None:
    """Apply ``PROVIDE_CONSENT_LEVEL`` if it is set.

    Called by ``setup_telemetry()`` and by the lazy ``get_logger()`` path, so an
    operator opt-out takes effect without a code change. Trimmed and upper-cased;
    an unset variable is a no-op (a level chosen in code survives) and an
    unrecognised value is ignored rather than raised — documented fail-open.
    """
    raw = os.environ.get("PROVIDE_CONSENT_LEVEL")
    if raw is None:
        return
    with contextlib.suppress(ValueError):
        set_consent_level(ConsentLevel(raw.strip().upper()))


def _reset_consent_for_tests() -> None:
    global _level
    with _lock:
        _level = ConsentLevel.FULL
