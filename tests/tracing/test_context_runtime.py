# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cross-context-safe OTel runtime context.

OpenTelemetry keeps "the current span" in a ``contextvars`` Token. A span whose
enter/exit straddle async-context boundaries — an async generator ``aclose()``d
from another task, a cancelled/GC'd coroutine — detaches its Token in a Context
different from the one it was created in. ``contextvars.Token.reset()`` then
raises ``ValueError`` and ``opentelemetry.context.detach`` logs a full traceback
per occurrence (the "Failed to detach context" storm). These tests pin the
mechanism and the guard that silences it, using the bare tracer
(``start_as_current_span``) so they exercise the fix for *every* span, not just
the :func:`provide.telemetry.tracing.span.span` helper.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from collections.abc import AsyncGenerator, Generator
from contextvars import Token
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.tracing import provider as provider_mod
from provide.telemetry.tracing.provider import _reset_tracing_for_tests, get_tracer

# Skip the whole module when the optional OTel SDK isn't installed — the release
# `build` job runs the suite without the `otel` extra, where the module-level
# OpenTelemetry imports below (and context_runtime, which imports OTel) would
# otherwise raise a collection error instead of a clean skip.
pytest.importorskip("opentelemetry.context.contextvars_context")

from opentelemetry import context as otel_context
from opentelemetry.context.contextvars_context import ContextVarsRuntimeContext

from provide.telemetry.tracing.context_runtime import (
    _SafeContextVarsRuntimeContext,
    install_safe_runtime_context,
)

if TYPE_CHECKING:
    from opentelemetry.context.context import Context

pytestmark = pytest.mark.otel


@pytest.fixture
def restore_runtime_context() -> Generator[None]:
    """Save/restore the global OTel runtime context across a test."""
    saved = otel_context._RUNTIME_CONTEXT
    try:
        yield
    finally:
        otel_context._RUNTIME_CONTEXT = saved


def _foreign_token(rc: _SafeContextVarsRuntimeContext) -> Token[Context]:
    """Create a Token by attaching inside a *different* contextvars.Context."""
    holder: dict[str, Token[Context]] = {}

    def _attach_in_child() -> None:
        holder["token"] = rc._current_context.set(rc.get_current())

    contextvars.copy_context().run(_attach_in_child)
    return holder["token"]


def test_safe_detach_swallows_cross_context_valueerror() -> None:
    """detach() on a token born in another Context must not raise."""
    rc = _SafeContextVarsRuntimeContext()
    token = _foreign_token(rc)
    # Vanilla ContextVarsRuntimeContext.reset(token) would raise ValueError here.
    rc.detach(token)  # must be a silent no-op


def test_safe_detach_normal_reset_path() -> None:
    """A well-formed attach/detach in the same Context still resets cleanly."""
    rc = _SafeContextVarsRuntimeContext()
    token = rc.attach(rc.get_current())
    rc.detach(token)


@pytest.mark.usefixtures("restore_runtime_context")
def test_install_is_idempotent() -> None:
    """First install swaps in the safe context; a second install is a no-op."""
    otel_context._RUNTIME_CONTEXT = ContextVarsRuntimeContext()
    assert install_safe_runtime_context() is True
    assert isinstance(otel_context._RUNTIME_CONTEXT, _SafeContextVarsRuntimeContext)
    assert install_safe_runtime_context() is False


@pytest.mark.usefixtures("restore_runtime_context")
def test_install_preserves_current_context() -> None:
    """Installing mid-flight carries the active Context over, not strands it."""
    otel_context._RUNTIME_CONTEXT = ContextVarsRuntimeContext()
    marker = otel_context.set_value("marker-key", "marker-val")
    token = otel_context.attach(marker)
    try:
        install_safe_runtime_context()
        assert otel_context.get_value("marker-key") == "marker-val"
    finally:
        otel_context.detach(token)


async def _drive_cross_context_span() -> None:
    """Open a span inside an async generator, then aclose() it from another task.

    The generator's ``start_as_current_span`` is torn down in the closing task's
    context — a different contextvars.Context than the one it was entered in.
    Uses the bare tracer so the reproduction is independent of any helper.
    """

    async def agen() -> AsyncGenerator[int, None]:
        with get_tracer().start_as_current_span("cross.context.teardown"):
            yield 1
            yield 2

    gen = agen()
    await gen.__anext__()  # enter the span in THIS task's context
    await asyncio.create_task(gen.aclose())  # exit it in a different task's context


def _capture_detach_logs() -> tuple[logging.Handler, list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []

    class _Catch(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Catch()
    return handler, records


@pytest.fixture
def real_tracer(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Resolve get_tracer() to a live SDK tracer without touching the global provider."""
    sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
    provider = sdk_trace.TracerProvider()
    test_tracer = provider.get_tracer("test")
    fake_api = SimpleNamespace(get_tracer=lambda *_a, **_k: test_tracer)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_provider_configured", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: fake_api)
    try:
        yield
    finally:
        provider.shutdown()


@pytest.mark.usefixtures("real_tracer", "restore_runtime_context")
def test_safe_runtime_context_silences_cross_context_detach() -> None:
    """The guard turns the per-teardown detach storm into silence.

    Without the safe context the default runtime context logs at least one
    "Failed to detach context"; with it installed, zero.
    """
    otel_logger = logging.getLogger("opentelemetry.context")
    handler, records = _capture_detach_logs()
    prev_level = otel_logger.level
    otel_logger.addHandler(handler)
    otel_logger.setLevel(logging.DEBUG)
    try:
        # Baseline: the vanilla runtime context emits the detach error.
        otel_context._RUNTIME_CONTEXT = ContextVarsRuntimeContext()
        asyncio.run(_drive_cross_context_span())
        assert len(records) >= 1, "expected the un-guarded detach storm to reproduce"

        # Guarded: the safe runtime context swallows it.
        records.clear()
        install_safe_runtime_context()
        asyncio.run(_drive_cross_context_span())
        assert records == []
    finally:
        otel_logger.removeHandler(handler)
        otel_logger.setLevel(prev_level)


@pytest.mark.usefixtures("restore_runtime_context")
def test_setup_tracing_installs_safe_runtime_context() -> None:
    """setup_tracing() wires the guard in so every service gets it for free."""
    _reset_tracing_for_tests()
    otel_context._RUNTIME_CONTEXT = ContextVarsRuntimeContext()
    try:
        provider_mod.setup_tracing(TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "true"}))
        assert isinstance(otel_context._RUNTIME_CONTEXT, _SafeContextVarsRuntimeContext)
    finally:
        provider_mod.shutdown_tracing()
        _reset_tracing_for_tests()
