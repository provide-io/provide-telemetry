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

import enum
import os
import threading
import warnings

from provide.telemetry.levels import LogSeverity, level_order

_CONSENT_ENV_VAR = "PROVIDE_CONSENT_LEVEL"


class ConsentLevel(enum.Enum):
    FULL = "FULL"
    FUNCTIONAL = "FUNCTIONAL"
    MINIMAL = "MINIMAL"
    NONE = "NONE"


_lock = threading.Lock()
_level: ConsentLevel = ConsentLevel.FULL
_invalid_env_warned = False


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
    operator opt-out takes effect without a code change. Trimmed and upper-cased.
    An unset or blank variable is a no-op (a level chosen in code survives). A
    set, non-empty, unrecognised value fails closed: consent becomes ``NONE``
    and a ``RuntimeWarning`` naming the value is emitted once per process. The
    variable is an opt-out control, and the one failure an opt-out must not
    have is a typo that silently leaves collection on.
    """
    raw = os.environ.get(_CONSENT_ENV_VAR)
    if raw is None:
        return
    text = raw.strip()
    if not text:
        return
    try:
        level = ConsentLevel(text.upper())
    except ValueError:
        level = ConsentLevel.NONE
        _warn_invalid_consent_env_once(raw)
    set_consent_level(level)


def _warn_invalid_consent_env_once(raw: str) -> None:
    global _invalid_env_warned
    with _lock:
        if _invalid_env_warned:
            return
        _invalid_env_warned = True
    message = (
        f"{_CONSENT_ENV_VAR}={raw!r} is not one of FULL, FUNCTIONAL, MINIMAL, NONE; consent set to NONE (fail-closed)"
    )
    warnings.warn(message, RuntimeWarning, stacklevel=3)  # pragma: no mutate — stacklevel is cosmetic


def _reset_consent_for_tests() -> None:
    global _invalid_env_warned, _level
    with _lock:
        _level = ConsentLevel.FULL
        _invalid_env_warned = False  # pragma: no mutate — None is an equivalent falsy reset
