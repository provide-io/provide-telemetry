# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""``filename``/``lineno`` must name the *caller's* line, on every call path.

``CallsiteParameterAdder`` finds the callsite by walking outwards from the
processor until it reaches a frame whose module name does not start with one of
its ignore prefixes.  Out of the box that list is ``structlog`` plus
``logging`` -- which says nothing about the wrapper frames *this* package puts
between user code and structlog:

* the ``_trace`` closure baked onto the bound logger class by
  ``_make_filtering_bound_logger``,
* ``_TraceWrapper.trace`` / ``_TraceWrapper.log``,
* ``_LazyLogger.trace`` / ``_LazyLogger.log`` behind the module-level ``logger``.

Without those prefixes the walk stops on the first wrapper it meets, so every
``.trace()`` in every consumer reported ``core.py:155`` and every ``.log()``
reported ``core.py:513``.  ``.debug()``/``.info()``/``.warning()``/``.error()``
were right only by accident: ``__getattr__`` hands back the *bound structlog
method*, so no wrapper frame is on the stack when it runs.

Every assertion here pins the record back to a line of THIS file, so a
regression anywhere in the wrapper chain fails loudly rather than quietly
attributing consumer logs to the library.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.levels import LogSeverity
from provide.telemetry.logger import core as logger_core

_THIS_FILE = Path(__file__)
_SOURCE_LINES = _THIS_FILE.read_text(encoding="utf-8").splitlines()

# mutmut runs the suite against a rewritten copy of the package under
# ``mutants/``, where every function is a trampoline that calls the original.
# That trampoline is the nearest frame outside logger.core, so exact callsite
# attribution is not observable there. Detected by where the package was
# imported from rather than by an environment variable, because stats
# collection runs before mutmut sets one.
_UNDER_MUTMUT = "mutants" in Path(logger_core.__file__).parts


def _configure() -> None:
    """Install a TRACE-level JSON pipeline with callsite parameters on."""
    base = TelemetryConfig.from_env()
    logging_cfg = dataclasses.replace(
        base.logging,
        level="TRACE",
        fmt="json",
        include_timestamp=False,
        include_caller=True,
        sanitize=False,
    )
    logger_core.configure_logging(dataclasses.replace(base, logging=logging_cfg), force=True)


def _records(capsys: Any) -> list[dict[str, Any]]:
    """The JSON records on stderr.

    Only lines that open a JSON object are parsed: the stdlib root logger
    shares this stream through ``_BackpressureFanoutHandler`` and renders
    ``%(message)s``, so unrelated plain-text records (asyncio's "Using
    selector: ..." during event-loop setup, for one) also land here.
    """
    return [json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")]


def _emit(body: Callable[[], None], capsys: Any) -> dict[str, Any]:
    """Run *body* against the configured pipeline and return its one record."""
    try:
        _configure()
        body()
    finally:
        logger_core._reset_logging_for_tests()
    records = _records(capsys)
    assert len(records) == 1, records
    return records[0]


def _assert_callsite_is_here(record: dict[str, Any], marker: str) -> None:
    """The record must name this test file and the very line holding *marker*.

    Under mutmut only the first half is checked. mutmut rewrites every function
    into a trampoline that calls the original, so the nearest frame outside
    ``logger.core`` is ``mutmut/mutation/trampoline.py`` rather than the caller,
    and no ignore list this package could ship would change that. The part that
    matters for the mutation gate still runs everywhere: a mutant that drops
    ``additional_ignores`` puts ``core.py`` back in that slot and is killed.
    """
    assert record["filename"] != "core.py", record
    if _UNDER_MUTMUT:
        return
    assert record["filename"] == _THIS_FILE.name, record
    source_line = _SOURCE_LINES[record["lineno"] - 1]
    assert marker in source_line, (record["lineno"], source_line)


def _log() -> Any:
    """Fetch a logger *inside* the emitting body.

    ``structlog.get_logger()`` hands back a lazy proxy that picks up whatever
    wrapper class is configured when it is first used, but ``.bind()`` resolves
    it immediately — so a logger built before ``_configure()`` would carry the
    previous test's level. This helper returns before the log call runs, so it
    never appears on the callsite stack.
    """
    return logger_core.get_logger("probe")


# ── the paths that were already correct (regression guards) ─────────────────


def test_info_reports_the_caller(capsys: Any) -> None:
    """`.info()` reaches structlog through __getattr__ -- no wrapper frame at all."""
    record = _emit(lambda: _log().info("callsite.info"), capsys)
    _assert_callsite_is_here(record, "callsite.info")


def test_debug_reports_the_caller(capsys: Any) -> None:
    record = _emit(lambda: _log().debug("callsite.debug"), capsys)
    _assert_callsite_is_here(record, "callsite.debug")


def test_warning_reports_the_caller(capsys: Any) -> None:
    record = _emit(lambda: _log().warning("callsite.warning"), capsys)
    _assert_callsite_is_here(record, "callsite.warning")


def test_error_reports_the_caller(capsys: Any) -> None:
    record = _emit(lambda: _log().error("callsite.error"), capsys)
    _assert_callsite_is_here(record, "callsite.error")


# ── .trace(): _TraceWrapper.trace -> the _trace closure ─────────────────────


def test_trace_reports_the_caller(capsys: Any) -> None:
    """Was `core.py:155` -- the `_trace` closure in _make_filtering_bound_logger."""
    record = _emit(lambda: _log().trace("callsite.trace"), capsys)
    _assert_callsite_is_here(record, "callsite.trace")


def test_bound_logger_trace_reports_the_caller(capsys: Any) -> None:
    """A `.bind()`-derived wrapper stacks the same two frames."""
    record = _emit(lambda: _log().bind(request_id="r1").trace("callsite.bound_trace"), capsys)
    _assert_callsite_is_here(record, "callsite.bound_trace")


# ── .log(level, ...): _TraceWrapper.log ─────────────────────────────────────


def test_log_with_severity_reports_the_caller(capsys: Any) -> None:
    """Was `core.py:513` -- the `self._logger.log(...)` forward in _TraceWrapper.log."""
    record = _emit(lambda: _log().log(LogSeverity.WARN, "callsite.log_severity"), capsys)
    _assert_callsite_is_here(record, "callsite.log_severity")


def test_log_with_level_string_reports_the_caller(capsys: Any) -> None:
    record = _emit(lambda: _log().log("error", "callsite.log_string"), capsys)
    _assert_callsite_is_here(record, "callsite.log_string")


def test_log_at_trace_reports_the_caller(capsys: Any) -> None:
    """`.log()`'s TRACE branch re-enters `.trace()` -- three wrapper frames deep."""
    record = _emit(lambda: _log().log("trace", "callsite.log_trace"), capsys)
    _assert_callsite_is_here(record, "callsite.log_trace")


# ── the module-level lazy `logger` proxy ────────────────────────────────────


def test_lazy_logger_info_reports_the_caller(capsys: Any) -> None:
    record = _emit(lambda: logger_core.logger.info("callsite.lazy_info"), capsys)
    _assert_callsite_is_here(record, "callsite.lazy_info")


def test_lazy_logger_trace_reports_the_caller(capsys: Any) -> None:
    """_LazyLogger.trace -> _TraceWrapper.trace -> the `_trace` closure."""
    record = _emit(lambda: logger_core.logger.trace("callsite.lazy_trace"), capsys)
    _assert_callsite_is_here(record, "callsite.lazy_trace")


def test_lazy_logger_log_reports_the_caller(capsys: Any) -> None:
    """_LazyLogger.log -> _TraceWrapper.log -> structlog."""
    record = _emit(lambda: logger_core.logger.log("warn", "callsite.lazy_log"), capsys)
    _assert_callsite_is_here(record, "callsite.lazy_log")


# ── only the two parameters the spec asks for ───────────────────────────────


def test_only_filename_and_lineno_are_added(capsys: Any) -> None:
    """Exactly two callsite parameters, not structlog's whole default set.

    ``CallsiteParameterAdder`` defaults to every parameter it knows —
    ``pathname``, ``module``, ``func_name``, thread and process ids among them.
    The spec asks for a filename and a line number
    (``PROVIDE_LOG_INCLUDE_CALLER``: "Add filename and line number to each log
    event"), and the other SDKs emit those two. Dropping the explicit
    ``parameters`` list would silently widen every record in the process.

    This holds under mutmut too, unlike the attribution assertions: it depends
    on which keys are present, not on which frame supplied them.
    """
    record = _emit(lambda: _log().info("callsite.parameters"), capsys)

    assert "filename" in record, record
    assert "lineno" in record, record
    unexpected = {
        "func_name",
        "module",
        "pathname",
        "process",
        "process_name",
        "repr_rv",
        "thread",
        "thread_name",
    } & record.keys()
    assert not unexpected, (unexpected, record)


# ── the library's own structlog logs still point at the library ─────────────


@pytest.mark.asyncio
async def test_library_internal_log_still_names_the_library(capsys: Any) -> None:
    """The ignore list must stay narrow enough for provide-telemetry's own
    diagnostics to keep naming their own source line.

    ``TelemetryMiddleware`` is the one in-package caller that logs through the
    structlog pipeline rather than the stdlib. Widening the ignore prefix from
    ``provide.telemetry.logger.core`` to ``provide.telemetry`` would skip its
    frame and blame whatever ASGI server happened to call it.
    """
    from provide.telemetry.asgi.middleware import TelemetryMiddleware

    async def _send(_message: dict[str, Any]) -> None:
        return None

    async def _receive() -> dict[str, Any]:
        return {"type": "noop"}

    async def _app(_scope: dict[str, Any], _recv: Any, _send_fn: Any) -> None:
        raise RuntimeError("boom")

    try:
        _configure()
        middleware = TelemetryMiddleware(_app, auto_slo=True)
        with pytest.raises(RuntimeError, match="boom"):
            await middleware({"type": "http", "path": "/err", "method": "GET", "headers": []}, _receive, _send)
    finally:
        logger_core._reset_logging_for_tests()

    failures = [r for r in _records(capsys) if r.get("message") == "http.request.unhandled_exception"]
    assert len(failures) == 1, failures
    assert failures[0]["filename"] == "middleware.py", failures[0]
