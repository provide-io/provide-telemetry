# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cross-context-safe OpenTelemetry runtime context.

OpenTelemetry stores "the current span" in a ``contextvars`` Token:
``start_as_current_span`` attaches the Token on enter and detaches it on exit.
``contextvars.Token.reset()`` raises ``ValueError: was created in a different
Context`` when the detach runs in a *different* ``contextvars.Context`` than the
attach. That happens whenever a span's lifetime straddles an async-context
boundary — an async generator ``aclose()``d from another task, a cancelled or
garbage-collected coroutine, a ``copy_context().run()`` boundary. OTel catches
the error but logs a full traceback per occurrence (``opentelemetry.context``
→ "Failed to detach context"), which floods long-running async services.

The owning context is being abandoned in every one of those cases, so there is
nothing to reset — the failed detach is benign. :class:`_SafeContextVarsRuntimeContext`
swallows *only* that cross-context ``ValueError`` and behaves identically
otherwise. :func:`install_safe_runtime_context` swaps it in globally;
``setup_tracing`` calls it so every provide.telemetry consumer is covered with
no code change.

This is installed by swapping ``opentelemetry.context._RUNTIME_CONTEXT`` at
setup time. The swap adopts the ContextVar already in use, so tasks that were
mid-span when ``setup_telemetry()`` ran keep their context. Services that can
guarantee import order may instead select it via the ``OTEL_PYTHON_CONTEXT``
entry point. Both ``_RUNTIME_CONTEXT`` and ``_current_context`` are private
OTel attributes: ``setup_tracing`` treats their absence as a degraded condition
(warns and continues) rather than a setup failure.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

# Imported as a submodule rather than `from opentelemetry import context`:
# opentelemetry is a namespace package, and the attribute form does not resolve
# for a type checker that can actually see the package. CI installs no otel
# extra before running mypy, so this only shows up locally.
import opentelemetry.context as _otel_context
from opentelemetry.context.contextvars_context import ContextVarsRuntimeContext

if TYPE_CHECKING:
    from contextvars import Token

    from opentelemetry.context.context import Context


class _SafeContextVarsRuntimeContext(ContextVarsRuntimeContext):
    """``ContextVarsRuntimeContext`` whose ``detach`` tolerates cross-context teardown."""

    def detach(self, token: Token[Context]) -> None:
        # A ValueError here means the Token was created in a different
        # contextvars.Context: the span's owning context is being torn down from
        # a foreign one (async-gen aclose() in another task, cancelled/GC'd
        # coroutine). That context is already abandoned, so there is nothing to
        # reset — drop it quietly instead of letting opentelemetry.context.detach
        # log a traceback per occurrence.
        with contextlib.suppress(ValueError):
            self._current_context.reset(token)


def install_safe_runtime_context() -> bool:
    """Swap OTel's runtime context for the cross-context-safe variant.

    Idempotent: returns ``True`` if it installed the safe context, ``False`` if
    it was already active.

    When the active runtime is OTel's own ``ContextVarsRuntimeContext`` the safe
    variant *adopts its ContextVar* rather than creating a new one. That is what
    makes a mid-flight install safe: every task — not only the caller — keeps its
    current ``Context``, and tokens handed out before the swap still ``reset``
    cleanly afterwards. A fresh ContextVar would carry over just the calling
    task's value and silently strand every other task at an empty context. Any
    other runtime implementation falls back to copying the caller's current
    ``Context``, which is the most that can be recovered from it.
    """
    current = _otel_context._RUNTIME_CONTEXT
    if isinstance(current, _SafeContextVarsRuntimeContext):
        return False
    safe = _SafeContextVarsRuntimeContext()
    if isinstance(current, ContextVarsRuntimeContext):
        safe._current_context = current._current_context
    else:
        safe._current_context.set(current.get_current())
    _otel_context._RUNTIME_CONTEXT = safe
    return True
