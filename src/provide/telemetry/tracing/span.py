# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Block-level span context manager and span attribute helpers.

``span()`` is the sync, attribute-aware counterpart to the ``@trace``
decorator: it opens a span around an arbitrary code block and shares the same
governance lifecycle (consent, sampling, backpressure, health) and
OTel↔contextvars correlation via :func:`_open_span`. Use it where a decorator
does not fit::

    with span("area.verb", kind="chromium") as sp:
        do_work()
        set_attrs(sp, item_count=len(items))

A plain ``with`` works inside ``async def`` too — the span's contextvars Token
is detached safely thanks to the cross-context-safe runtime context installed
by ``setup_tracing`` (see :mod:`provide.telemetry.tracing.context_runtime`).

Attribute handling (shared by ``span``, :func:`set_attrs`, and the per-call
``**attrs``): ``None`` values are dropped (OTel rejects them); primitives and
sequences of primitives pass through; anything else is stringified so the
field is still recorded rather than silently dropped by the SDK. Every helper
is safe on the no-op span returned when tracing is disabled.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from provide.telemetry.tracing.decorators import _open_span


@contextmanager
def span(name: str, /, **attrs: Any) -> Iterator[Any]:
    """Open a span named ``name`` as a context manager, yielding the span.

    Exceptions propagate (the span records them and is marked ERROR before
    re-raising). Shares the ``@trace`` governance lifecycle and no-ops cleanly
    when tracing is disabled.
    """
    with _open_span(name) as sp:
        for key, value in attrs.items():
            if value is not None:
                _set_span_attr(sp, key, value)
        yield sp


def set_attrs(sp: Any, /, **attrs: Any) -> None:
    """Set multiple attributes on a live span, coercing values and dropping ``None``.

    Use mid-block when attribute values are only known after the span opens.
    Safe on a no-op span (drops silently).
    """
    for key, value in attrs.items():
        if value is not None:
            _set_span_attr(sp, key, value)


def record_exception(sp: Any, exc: BaseException) -> None:
    """Attach ``exc`` to ``sp`` and mark the span ERROR, without re-raising.

    For the ``except`` block where you want the failure recorded but control to
    continue. Safe on a no-op span (no ``record_exception``/``set_status`` →
    drop) and never raises out of instrumentation.
    """
    record = getattr(sp, "record_exception", None)
    if record is not None:
        with contextlib.suppress(Exception):
            record(exc)
    set_status = getattr(sp, "set_status", None)
    if set_status is not None:
        with contextlib.suppress(Exception):
            # Imported lazily so this module never hard-depends on OTel.
            from opentelemetry.trace import Status, StatusCode

            set_status(Status(StatusCode.ERROR, str(exc)[:200]))


def _set_span_attr(sp: Any, key: str, value: Any) -> None:
    """Set one attribute on ``sp``, coercing to an OTel-accepted type.

    Safe on a no-op span (no ``set_attribute`` → drop) and on a span whose
    ``set_attribute`` raises (swallowed, so instrumentation never breaks code).
    """
    setter = getattr(sp, "set_attribute", None)
    if setter is None:
        return
    if isinstance(value, str | bool | int | float):
        coerced: Any = value
    elif isinstance(value, list | tuple) and all(isinstance(v, str | bool | int | float) for v in value):
        coerced = list(value)
    else:
        coerced = str(value)
    # A non-standard span whose set_attribute raises must never break the
    # instrumented code path — recording an attribute is best-effort.
    with contextlib.suppress(Exception):
        setter(key, coerced)
