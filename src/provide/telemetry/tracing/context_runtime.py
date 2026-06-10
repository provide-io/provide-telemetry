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
setup time (before any spans exist). Services that can guarantee import order
may instead select it via the ``OTEL_PYTHON_CONTEXT`` entry point.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from opentelemetry import context as _otel_context
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
    it was already active. Carries the active ``Context`` over so installing
    mid-flight never strands an in-flight span.
    """
    current = _otel_context._RUNTIME_CONTEXT
    if isinstance(current, _SafeContextVarsRuntimeContext):
        return False
    safe = _SafeContextVarsRuntimeContext()
    safe._current_context.set(current.get_current())
    _otel_context._RUNTIME_CONTEXT = safe
    return True
