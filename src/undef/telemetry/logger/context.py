# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Context binding helpers for logs and traces."""

from __future__ import annotations

import contextvars

_context: contextvars.ContextVar[dict[str, object] | None] = contextvars.ContextVar("telemetry_context", default=None)


def get_context() -> dict[str, object]:
    raw = _context.get()
    return dict(raw or {})


def bind_context(**values: object) -> None:
    ctx = get_context()
    ctx.update(values)
    _context.set(ctx)


def unbind_context(*keys: str) -> None:
    ctx = get_context()
    for key in keys:
        ctx.pop(key, None)
    _context.set(ctx)


def clear_context() -> None:
    _context.set({})


def restore_context(snapshot: dict[str, object]) -> None:
    _context.set(snapshot)


def bind_session_context(session_id: str) -> None:
    """Bind a session ID that propagates across all telemetry events."""
    bind_context(session_id=session_id)


def get_session_id() -> str | None:
    """Return the current session ID, or None if not set."""
    ctx = _context.get()
    val = ctx.get("session_id") if ctx else None
    return str(val) if val is not None else None


def clear_session_context() -> None:
    """Clear the session ID."""
    unbind_context("session_id")


ContextToken = contextvars.Token[dict[str, object] | None]


def save_context() -> ContextToken:
    """Snapshot the current context, returning a token for zero-copy reset."""
    return _context.set(_context.get())  # pragma: no mutate


def reset_context(token: ContextToken) -> None:
    """Restore context to the point captured by save_context()."""
    _context.reset(token)
