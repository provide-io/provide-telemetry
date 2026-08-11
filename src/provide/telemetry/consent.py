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


# The two provably-equivalent literals from _rank, hoisted so each carries its
# own suppression instead of one bare pragma silencing the whole expression.
# A bare pragma applies to the entire line, so it would also have hidden the
# `.upper()` -> `.lower()` swap and the `or` -> `and` mutation, both of which
# genuinely change what should_allow() returns.
#
# Placeholder for a missing level: "" and any other string absent from
# _LOG_LEVEL_ORDER resolve to the same lookup miss.
_MISSING_LEVEL_PLACEHOLDER = ""  # pragma: no mutate — any string absent from _LOG_LEVEL_ORDER is the same lookup miss
# Miss sentinel: 0 and 1 both sit below every threshold this is compared
# against (WARNING=3, ERROR=4).
_UNKNOWN_LEVEL_RANK = 0  # pragma: no mutate — 0 and 1 both rank below every consent threshold (WARNING=3, ERROR=4)


def _rank(log_level: str | None) -> int:
    """Order a log level for consent comparisons; unknown levels sort lowest."""
    return _LOG_LEVEL_ORDER.get((log_level or _MISSING_LEVEL_PLACEHOLDER).upper(), _UNKNOWN_LEVEL_RANK)


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
