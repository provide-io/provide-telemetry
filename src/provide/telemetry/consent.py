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


# Default consent when PROVIDE_CONSENT_LEVEL is unset. Suppressed on its own
# line rather than on the read below: the default is upper-cased along with the
# env value so a case mutation cannot change the result, and any other mutation
# of it yields a string ConsentLevel() rejects, leaving the already-FULL default
# in place. The env var *name* and the `.upper()` on the read are not equivalent
# and stay mutable.
_DEFAULT_CONSENT_LEVEL = "FULL"  # pragma: no mutate — upper-cased with the env value; any other literal is rejected by ConsentLevel, leaving the FULL default


def _load_consent_from_env() -> None:
    raw = os.environ.get("PROVIDE_CONSENT_LEVEL", _DEFAULT_CONSENT_LEVEL).strip().upper()
    with contextlib.suppress(ValueError):
        set_consent_level(ConsentLevel(raw))


def _reset_consent_for_tests() -> None:
    global _level
    with _lock:
        _level = ConsentLevel.FULL
