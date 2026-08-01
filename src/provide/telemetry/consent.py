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


def _rank(log_level: str | None) -> int:
    """Order a log level for consent comparisons; unknown levels sort lowest.

    Both mutations mutmut generates here are provably equivalent and so are
    suppressed rather than tested: the placeholder for a missing level ("" vs any
    other string absent from the map) resolves to the same lookup miss, and the
    miss sentinel (0 vs 1) sits below every threshold this is compared against
    (WARNING=3, ERROR=4). The pragma must be on a single-line statement to apply.
    """
    return _LOG_LEVEL_ORDER.get((log_level or "").upper(), 0)  # pragma: no mutate


def should_allow(signal: str, log_level: str | None = None) -> bool:
    with _lock:
        level = _level

    if level == ConsentLevel.FULL:
        return True
    if level == ConsentLevel.NONE:
        return False
    if level == ConsentLevel.FUNCTIONAL:
        if signal == "logs":
            return _rank(log_level) >= _LOG_LEVEL_ORDER["WARNING"]
        return signal != "context"  # traces and metrics allowed; context blocked
    # MINIMAL
    if signal == "logs":
        return _rank(log_level) >= _LOG_LEVEL_ORDER["ERROR"]
    return False  # traces/metrics/context blocked at MINIMAL


def _load_consent_from_env() -> None:
    # The default is upper-cased along with the env value, so a case mutation of
    # the literal cannot change the result — provably equivalent.
    raw = os.environ.get("PROVIDE_CONSENT_LEVEL", "FULL").strip().upper()  # pragma: no mutate
    with contextlib.suppress(ValueError):
        set_consent_level(ConsentLevel(raw))


def _reset_consent_for_tests() -> None:
    global _level
    with _lock:
        _level = ConsentLevel.FULL
