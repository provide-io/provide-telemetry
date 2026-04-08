# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Consent-aware telemetry collection — strippable governance module.

When deleted, all signals pass through unchanged (no hook or gate installed).
"""

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


class ConsentLevel(enum.Enum):
    FULL = "FULL"
    FUNCTIONAL = "FUNCTIONAL"
    MINIMAL = "MINIMAL"
    NONE = "NONE"


_LOG_LEVEL_ORDER = {"TRACE": 0, "DEBUG": 1, "INFO": 2, "WARNING": 3, "ERROR": 4, "CRITICAL": 5}

_lock = threading.Lock()
_level: ConsentLevel = ConsentLevel.FULL


def set_consent_level(level: ConsentLevel) -> None:
    global _level
    with _lock:
        _level = level


def get_consent_level() -> ConsentLevel:
    with _lock:
        return _level


def should_allow(signal: str, log_level: str | None = None) -> bool:
    with _lock:
        level = _level

    if level == ConsentLevel.FULL:
        return True
    if level == ConsentLevel.NONE:
        return False
    if level == ConsentLevel.FUNCTIONAL:
        if signal == "logs":
            return (  # pragma: no mutate
                _LOG_LEVEL_ORDER.get((log_level or "").upper(), 0) >= _LOG_LEVEL_ORDER["WARNING"]  # pragma: no mutate
            )
        return signal != "context"  # traces and metrics allowed; context blocked
    # MINIMAL
    if signal == "logs":
        return _LOG_LEVEL_ORDER.get((log_level or "").upper(), 0) >= _LOG_LEVEL_ORDER["ERROR"]  # pragma: no mutate
    return False  # traces/metrics/context blocked at MINIMAL


def _load_consent_from_env() -> None:
    raw = os.environ.get("PROVIDE_CONSENT_LEVEL", "FULL").strip().upper()  # pragma: no mutate
    with contextlib.suppress(ValueError):
        set_consent_level(ConsentLevel(raw))


def _reset_consent_for_tests() -> None:
    global _level
    with _lock:
        _level = ConsentLevel.FULL
