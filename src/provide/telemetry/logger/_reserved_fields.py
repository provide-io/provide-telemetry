# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Reporting reserved root fields whose caller value a stamped value replaced.

See reserved_root_fields.replacement_reporting in spec/telemetry-api.yaml. A
replacement that loses data adds to the reserved_field_replacements health
counter, and the first one for each field in the process logs one warning
naming the field, never the caller's value.

The trace ids are stamped before admission and the identity fields after it,
so a trace-id replacement is noted where it happens and reported together with
the identity fields once the record is admitted. The warning is logged from
there, so it reaches the output just before the record it explains. A record refused by sampling,
consent or backpressure is therefore neither counted nor warned about.
"""

from __future__ import annotations

import threading

# Canonical order: the order replacements are counted and warned about.
RESERVED_FIELDS = ("service", "env", "version", "trace_id", "span_id")
WARNING_EVENT = "logger.reserved_field.replaced"

_lock = threading.Lock()
_warned: set[str] = set()


class _ThreadState(threading.local):
    # Trace-id replacements noted for the record this thread is processing.
    # Overwritten at the start of every record, so one a later stage refused
    # never carries over to the next.
    pending: tuple[str, ...] = ()
    # Set while this thread logs a warning. The warning is an ordinary record
    # and runs the same stamping, so a reserved field in bound context would
    # otherwise count a second time, against a record the caller never wrote.
    warning = False


_state = _ThreadState()


def note_trace_replacements(fields: tuple[str, ...]) -> None:
    """Record the trace-id fields the current record's stamping replaced."""
    _state.pending = fields


def take_trace_replacements() -> tuple[str, ...]:
    """The noted trace-id replacements for the current record, clearing them."""
    pending = _state.pending
    _state.pending = ()
    return pending


def report(fields: set[str]) -> None:
    """Count *fields* as replaced, warning once per field per process."""
    if not fields or _state.warning:
        return
    # Imported here: a bare `import provide.telemetry` must not load health.
    from provide.telemetry.health import increment_reserved_field_replacements

    increment_reserved_field_replacements(len(fields))
    with _lock:
        first = [field for field in RESERVED_FIELDS if field in fields and field not in _warned]
        _warned.update(first)
    if not first:
        return
    # Imported here: the logger core imports this module.
    from provide.telemetry.logger.core import get_logger

    logger = get_logger("provide.telemetry.logger")
    _state.warning = True
    try:
        for field in first:
            logger.warning(WARNING_EVENT, field=field)
    finally:
        _state.warning = False


def _reset_reserved_fields_for_tests() -> None:
    with _lock:
        _warned.clear()
    _state.pending = ()
    _state.warning = False
