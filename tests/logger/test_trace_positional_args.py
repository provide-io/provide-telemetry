# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""`.trace()` must accept the same call shapes as every other level.

structlog's bound-logger methods are ``(event, *args, **kw)`` and interpolate
``event % args``, so ``log.info("chunk %d of %s", 3, "reader")`` works. Three
hand-written ``trace`` definitions used to narrow that to ``(event, **kwargs)``,
which made demoting an ``info`` call to ``trace`` — the obvious way to quiet a
noisy log — a latent ``TypeError``. Worse, the raise happened even when TRACE
was *disabled* and the call was a guaranteed no-op: zero logging value, full
crash risk.

The three narrowing sites were ``_TraceWrapper.trace``, ``_LazyLogger.trace``,
and the ``_trace`` closure inside ``_make_filtering_bound_logger``. Fixing any
one alone only relocates the error, so these tests exercise all three entry
points: the bound logger from ``get_logger()``, the module-level lazy ``logger``,
and a ``.bind()``-derived wrapper.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger import core as logger_core

_LEVELS = ("trace", "debug", "info", "warning", "error", "critical")


def _run_at_level(level: str, body: Callable[[], None], capsys: Any) -> list[dict[str, Any]]:
    """Configure logging at *level*, run *body*, return the emitted JSON records."""
    base = TelemetryConfig.from_env()
    logging_cfg = dataclasses.replace(
        base.logging,
        level=level,
        fmt="json",
        include_timestamp=False,
        sanitize=False,
    )
    config = dataclasses.replace(base, logging=logging_cfg)
    try:
        logger_core.configure_logging(config, force=True)
        body()
    finally:
        logger_core._reset_logging_for_tests()
    out = capsys.readouterr().err.strip()
    return [json.loads(line) for line in out.splitlines() if line.strip()]


# ── TRACE enabled: positional args must interpolate ─────────────────────────


def test_bound_logger_trace_interpolates_positional_args(capsys: Any) -> None:
    """Kills the narrowing on the `_trace` closure in _make_filtering_bound_logger."""
    records = _run_at_level(
        "TRACE",
        lambda: logger_core.get_logger("probe").trace("chunk %d of %s", 7, "reader"),
        capsys,
    )
    assert len(records) == 1
    assert records[0]["message"] == "chunk 7 of reader"


def test_module_logger_trace_interpolates_positional_args(capsys: Any) -> None:
    """Kills the narrowing on _LazyLogger.trace — the module-level `logger`."""
    records = _run_at_level(
        "TRACE",
        lambda: logger_core.logger.trace("chunk %d of %s", 7, "reader"),
        capsys,
    )
    assert len(records) == 1
    assert records[0]["message"] == "chunk 7 of reader"


def test_bound_wrapper_trace_interpolates_positional_args(capsys: Any) -> None:
    """Kills the narrowing on _TraceWrapper.trace, reached through .bind()."""
    records = _run_at_level(
        "TRACE",
        lambda: logger_core.get_logger("probe").bind(rid="r1").trace("chunk %d of %s", 7, "reader"),
        capsys,
    )
    assert len(records) == 1
    assert records[0]["message"] == "chunk 7 of reader"
    assert records[0]["rid"] == "r1"


def test_trace_still_marks_records_as_trace_with_positional_args(capsys: Any) -> None:
    """Positional support must not drop the `_trace` marker the level depends on."""
    records = _run_at_level(
        "TRACE",
        lambda: logger_core.get_logger("probe").trace("chunk %d", 7),
        capsys,
    )
    assert records[0]["_trace"] is True


# ── TRACE disabled: the no-op must stay a no-op, not a TypeError ────────────


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda: logger_core.get_logger("probe").trace("chunk %d", 7), id="bound"),
        pytest.param(lambda: logger_core.logger.trace("chunk %d", 7), id="lazy"),
        pytest.param(
            lambda: logger_core.get_logger("probe").bind(rid="r1").trace("chunk %d", 7),
            id="bound-wrapper",
        ),
    ],
)
def test_trace_with_positional_args_is_a_silent_noop_when_disabled(call: Callable[[], None], capsys: Any) -> None:
    """At INFO the call has zero logging value; it must not raise either."""
    assert _run_at_level("INFO", call, capsys) == []


# ── Cross-level parity: one contract, every level ───────────────────────────


@pytest.mark.parametrize("level_method", _LEVELS)
def test_every_level_accepts_positional_format_args(level_method: str, capsys: Any) -> None:
    """`.trace` was the sole outlier — pin the whole set so it cannot drift back."""
    records = _run_at_level(
        "TRACE",
        lambda: getattr(logger_core.get_logger("probe"), level_method)("chunk %d of %s", 7, "reader"),
        capsys,
    )
    assert len(records) == 1
    assert records[0]["message"] == "chunk 7 of reader"


@pytest.mark.parametrize("level_method", _LEVELS)
def test_every_level_accepts_event_plus_keywords(level_method: str, capsys: Any) -> None:
    """The kwargs-only shape must keep working at every level."""
    records = _run_at_level(
        "TRACE",
        lambda: getattr(logger_core.get_logger("probe"), level_method)("io.chunk.read", size=7),
        capsys,
    )
    assert len(records) == 1
    assert records[0]["message"] == "io.chunk.read"
    assert records[0]["size"] == 7
