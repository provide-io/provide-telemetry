# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The canonical severity ladder and the single string-to-level converter.

Lives at the package root rather than under ``logger/`` so that ``config`` and
``consent`` can use it without importing the logger package, which imports
``config`` in turn.

Python's drift was two separate tables — ``_LEVEL_NAME_TO_NUMERIC`` in
``logger/core.py`` and ``_FAST_LEVEL_LOOKUP`` in ``logger/processors.py`` —
neither of which knew ``WARN``, plus a third ordering in ``consent.py``.
``config`` rejected ``WARN`` outright while Rust accepted it.

See the ``log_levels`` section of ``spec/behavioral_fixtures.yaml`` for the
cross-language contract.
"""

from __future__ import annotations

import logging
from enum import IntEnum

__all__ = [
    "LogSeverity",
    "level_order",
    "parse_level",
    "to_stdlib_level",
    "try_parse_level",
]

#: Numeric level for TRACE, which the stdlib does not define.
TRACE = 5


class LogSeverity(IntEnum):
    """The canonical ladder. The value is the rank, so members compare directly.

    ``WARNING`` and ``FATAL`` are deliberately absent: they are spellings
    resolved by :func:`try_parse_level`, not members. Admitting an alias as a
    member is how ``Warn`` and ``Warning`` both ended up on the public C#
    Logger surface.
    """

    TRACE = 0
    DEBUG = 1
    INFO = 2
    WARN = 3
    ERROR = 4
    CRITICAL = 5

    @property
    def canonical_name(self) -> str:
        """The canonical uppercase spelling."""
        return _CANONICAL_NAMES[self.value]

    @property
    def stdlib_level(self) -> int:
        """The :mod:`logging` numeric level that carries this severity."""
        return _STDLIB_LEVELS[self.value]


# Indexed by rank, so a mutated index is a wrong answer rather than a KeyError.
_CANONICAL_NAMES: tuple[str, ...] = ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "CRITICAL")

_STDLIB_LEVELS: tuple[int, ...] = (
    TRACE,
    logging.DEBUG,
    logging.INFO,
    logging.WARNING,
    logging.ERROR,
    logging.CRITICAL,
)

# Every accepted spelling, canonical and alias alike. Keys are uppercase; the
# lookup uppercases its input.
_TABLE: dict[str, LogSeverity] = {
    "TRACE": LogSeverity.TRACE,
    "DEBUG": LogSeverity.DEBUG,
    "INFO": LogSeverity.INFO,
    "WARN": LogSeverity.WARN,
    "ERROR": LogSeverity.ERROR,
    "CRITICAL": LogSeverity.CRITICAL,
    "WARNING": LogSeverity.WARN,
    "FATAL": LogSeverity.CRITICAL,
}


def try_parse_level(text: str | None) -> LogSeverity | None:
    """Resolve a level string, or ``None`` when it is not recognised.

    Surrounding whitespace is trimmed and comparison is case-insensitive.
    """
    if text is None:
        return None
    return _TABLE.get(text.strip().upper())


def parse_level(text: str | None, fallback: LogSeverity = LogSeverity.INFO) -> LogSeverity:
    """Resolve a level string, substituting ``fallback`` when unrecognised.

    The fallback is a parameter rather than a hidden constant so the
    substitution is visible at the call site.
    """
    parsed = try_parse_level(text)
    if parsed is None:
        return fallback
    return parsed


def level_order(text: str | None) -> int:
    """Rank a level string, with unrecognised values ranking INFO."""
    return int(parse_level(text))


def to_stdlib_level(level: LogSeverity | str | int) -> int:
    """Coerce any accepted level form to a :mod:`logging` numeric level.

    A :class:`LogSeverity` resolves through the ladder and a string through the
    shared table. A bare ``int`` is passed through as a stdlib level, which is
    what structlog's own ``log()`` has always taken -- so existing callers that
    pass ``logging.WARNING`` keep working.

    The :class:`LogSeverity` check has to come first: ``LogSeverity`` is an
    :class:`~enum.IntEnum`, so every member is also an ``int``. Its values are
    ranks (0-5), not stdlib levels, and ``LogSeverity.CRITICAL`` would
    otherwise pass through as the stdlib's TRACE.
    """
    if isinstance(level, LogSeverity):
        return level.stdlib_level
    if isinstance(level, str):
        return parse_level(level).stdlib_level
    return level
