# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Transcribes the log_levels section of spec/behavioral_fixtures.yaml.

The canonical ladder, the alias table and the unrecognised-token fallback are
cross-language contracts, not Python choices. Python's own drift was two
separate numeric tables -- one in logger/core.py, one in logger/processors.py
-- neither of which knew WARN, plus a third ordering in consent.py and a
config validator that rejected WARN outright while Rust accepted it.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Callable
from typing import Any

import pytest

from provide.telemetry import consent
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.exceptions import ConfigurationError
from provide.telemetry.levels import (
    TRACE,
    LogSeverity,
    level_order,
    parse_level,
    to_stdlib_level,
    try_parse_level,
)
from provide.telemetry.logger import core as logger_core

CANONICAL = [
    (LogSeverity.TRACE, 0, "TRACE", TRACE),
    (LogSeverity.DEBUG, 1, "DEBUG", logging.DEBUG),
    (LogSeverity.INFO, 2, "INFO", logging.INFO),
    (LogSeverity.WARN, 3, "WARN", logging.WARNING),
    (LogSeverity.ERROR, 4, "ERROR", logging.ERROR),
    (LogSeverity.CRITICAL, 5, "CRITICAL", logging.CRITICAL),
]


@pytest.mark.parametrize(("severity", "order", "name", "stdlib"), CANONICAL)
def test_parity_log_levels_canonical_ladder(severity: LogSeverity, order: int, name: str, stdlib: int) -> None:
    assert int(severity) == order
    assert severity.canonical_name == name
    assert severity.stdlib_level == stdlib


def test_parity_log_levels_ladder_has_exactly_six_members() -> None:
    assert len(LogSeverity) == 6


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ERROR", LogSeverity.ERROR),
        ("error", LogSeverity.ERROR),
        ("CrItIcAl", LogSeverity.CRITICAL),
        ("  warn  ", LogSeverity.WARN),
        ("warning", LogSeverity.WARN),
        ("WARNING", LogSeverity.WARN),
        ("FATAL", LogSeverity.CRITICAL),
        ("CRITICAL", LogSeverity.CRITICAL),
        ("TRACE", LogSeverity.TRACE),
        ("DEBUG", LogSeverity.DEBUG),
        ("INFO", LogSeverity.INFO),
    ],
)
def test_parity_log_levels_recognised_spellings(text: str, expected: LogSeverity) -> None:
    assert try_parse_level(text) is expected
    assert parse_level(text) is expected
    assert level_order(text) == int(expected)


@pytest.mark.parametrize("text", ["warnn", "warns", "", "   ", None])
def test_parity_log_levels_unrecognised_fall_back_to_info(text: str | None) -> None:
    assert try_parse_level(text) is None
    assert parse_level(text) is LogSeverity.INFO
    assert level_order(text) == int(LogSeverity.INFO)


def test_parity_log_levels_fallback_applies_only_to_unrecognised_input() -> None:
    assert parse_level("warnn", LogSeverity.ERROR) is LogSeverity.ERROR
    assert parse_level("debug", LogSeverity.ERROR) is LogSeverity.DEBUG


def test_parity_log_levels_ordering() -> None:
    # CRITICAL is a distinct severity, not a spelling of ERROR.
    assert parse_level("CRITICAL") > parse_level("ERROR")
    assert parse_level("WARNING") == parse_level("WARN")
    assert parse_level("FATAL") == parse_level("CRITICAL")
    assert parse_level("TRACE") < parse_level("DEBUG")


def test_parity_log_levels_to_stdlib_level_accepts_every_form() -> None:
    assert to_stdlib_level(LogSeverity.WARN) == logging.WARNING
    assert to_stdlib_level("warning") == logging.WARNING
    assert to_stdlib_level("nonsense") == logging.INFO
    # A bare int is a stdlib level, which is what structlog's own log() takes.
    assert to_stdlib_level(logging.ERROR) == logging.ERROR
    # LogSeverity is an IntEnum, so the member check must precede the int
    # check: CRITICAL's rank is 5, which is the stdlib's TRACE.
    assert to_stdlib_level(LogSeverity.CRITICAL) == logging.CRITICAL
    assert to_stdlib_level(5) == TRACE


def test_parity_log_levels_consent_ranks_through_the_shared_table() -> None:
    consent.set_consent_level(consent.ConsentLevel.FUNCTIONAL)
    try:
        assert not consent.should_allow("logs", "INFO")
        assert consent.should_allow("logs", "WARN")
        assert consent.should_allow("logs", "WARNING")
        # FATAL used to be unrecognised here, so it ranked 0 and was dropped --
        # the most severe record in the ladder discarded as if it were the least.
        assert consent.should_allow("logs", "FATAL")
        # An unrecognised level now ranks INFO rather than 0/TRACE. Both sit
        # below this gate, so the decision is unchanged.
        assert not consent.should_allow("logs", "nonsense")
        assert not consent.should_allow("logs", None)
    finally:
        consent.set_consent_level(consent.ConsentLevel.FULL)


@pytest.mark.parametrize("spelling", ["TRACE", "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL", "FATAL"])
def test_parity_log_levels_config_accepts_every_spelling(monkeypatch: pytest.MonkeyPatch, spelling: str) -> None:
    # WARN and FATAL were rejected here while Rust accepted both.
    monkeypatch.setenv("PROVIDE_LOG_LEVEL", spelling)
    assert TelemetryConfig.from_env().logging.level == spelling


def test_parity_log_levels_config_rejects_outside_the_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDE_LOG_LEVEL", "LOUD")
    with pytest.raises(ConfigurationError, match="invalid log level"):
        TelemetryConfig.from_env()


# ── the level-parameterised door ────────────────────────────────────────────


def _emit_at_trace(body: Callable[[], None], capsys: Any) -> list[dict[str, Any]]:
    """Run *body* with logging at TRACE in JSON, returning the emitted records."""
    base = TelemetryConfig.from_env()
    logging_cfg = dataclasses.replace(base.logging, level="TRACE", fmt="json", include_timestamp=False, sanitize=False)
    try:
        logger_core.configure_logging(dataclasses.replace(base, logging=logging_cfg), force=True)
        body()
    finally:
        logger_core._reset_logging_for_tests()
    out = capsys.readouterr().err.strip()
    return [json.loads(line) for line in out.splitlines() if line.strip()]


@pytest.mark.parametrize(
    ("severity", "rendered"),
    [
        # The canonical uppercase ladder, identical to the other four ports.
        # TRACE still carries _trace -- the pipeline floors structlog at DEBUG
        # and implements .trace() as debug(_trace=True) -- but the level it
        # publishes is TRACE, not the DEBUG it arrives as.
        (LogSeverity.TRACE, "TRACE"),
        (LogSeverity.DEBUG, "DEBUG"),
        (LogSeverity.INFO, "INFO"),
        (LogSeverity.WARN, "WARN"),
        (LogSeverity.ERROR, "ERROR"),
        (LogSeverity.CRITICAL, "CRITICAL"),
    ],
)
def test_parity_log_levels_log_emits_at_the_given_level(severity: LogSeverity, rendered: str, capsys: Any) -> None:
    # The rendered spelling is structlog's, untouched by this change: WARN
    # still renders "warning" here exactly as logger.warning() always has.
    records = _emit_at_trace(lambda: logger_core.get_logger("probe").log(severity, "level.probe"), capsys)
    assert [r["level"] for r in records] == [rendered]
    assert records[0].get("_trace", False) is (severity is LogSeverity.TRACE)


def test_parity_log_levels_log_accepts_a_level_string(capsys: Any) -> None:
    # structlog's own log() takes a stdlib numeric, so a string raised
    # TypeError on the `level < min_level` comparison inside the bound logger.
    records = _emit_at_trace(lambda: logger_core.get_logger("probe").log("warning", "level.probe"), capsys)
    assert [r["level"] for r in records] == ["WARN"]


def test_parity_log_levels_log_accepts_a_stdlib_numeric(capsys: Any) -> None:
    records = _emit_at_trace(lambda: logger_core.get_logger("probe").log(logging.ERROR, "level.probe"), capsys)
    assert [r["level"] for r in records] == ["ERROR"]


def test_parity_log_levels_log_collapses_the_adapter_chain(capsys: Any) -> None:
    """The motivating case: a component reports (level, message) as data."""

    def body() -> None:
        log = logger_core.get_logger("adapter")

        def on_log(level: str, message: str) -> None:
            log.log(parse_level(level), message)

        for level, message in [
            ("debug", "a"),
            ("warn", "b"),
            ("warning", "c"),
            ("error", "d"),
            ("fatal", "e"),
            ("nonsense", "f"),
        ]:
            on_log(level, message)

    records = _emit_at_trace(body, capsys)
    assert [r["level"] for r in records] == [
        "DEBUG",
        "WARN",
        "WARN",
        "ERROR",
        "CRITICAL",
        "INFO",
    ]


def test_parity_log_levels_lazy_logger_exposes_the_same_door(capsys: Any) -> None:
    from provide.telemetry import logger as lazy_logger

    records = _emit_at_trace(lambda: lazy_logger.log(LogSeverity.CRITICAL, "level.probe"), capsys)
    assert [r["level"] for r in records] == ["CRITICAL"]


@pytest.mark.parametrize(
    ("severity", "rendered"),
    [(LogSeverity.TRACE, "TRACE"), (LogSeverity.WARN, "WARN")],
)
def test_parity_log_levels_log_interpolates_args_and_keeps_fields(
    severity: LogSeverity, rendered: str, capsys: Any
) -> None:
    """Both branches of the door forward *args and **kwargs unchanged.

    TRACE takes the .trace() branch and everything else takes structlog's
    log(); each forwards separately, so both need exercising or a mutant that
    drops one of them survives.
    """
    records = _emit_at_trace(
        lambda: logger_core.get_logger("probe").log(severity, "chunk %d of %s", 7, "reader", request_id="abc"),
        capsys,
    )
    assert len(records) == 1
    assert records[0]["message"] == "chunk 7 of reader"
    assert records[0]["request_id"] == "abc"
    assert records[0]["level"] == rendered


@pytest.mark.parametrize("severity", [LogSeverity.TRACE, LogSeverity.ERROR])
def test_parity_log_levels_lazy_logger_forwards_args_and_fields(severity: LogSeverity, capsys: Any) -> None:
    from provide.telemetry import logger as lazy_logger

    records = _emit_at_trace(
        lambda: lazy_logger.log(severity, "chunk %d of %s", 7, "reader", request_id="abc"),
        capsys,
    )
    assert len(records) == 1
    assert records[0]["message"] == "chunk 7 of reader"
    assert records[0]["request_id"] == "abc"


def test_parity_log_levels_canonicalize_level_leaves_a_levelless_record_alone() -> None:
    """A record that never reached add_log_level has no level to canonicalise.

    Reachable because the processor is a plain callable other pipelines can
    invoke; without the guard it would write "INFO" onto a record that
    deliberately carries no level.
    """
    from provide.telemetry.logger.processors import canonicalize_level

    event_dict: dict[str, Any] = {"event": "no.level.here"}
    assert canonicalize_level(None, "info", event_dict) == {"event": "no.level.here"}
    assert "level" not in event_dict


def test_parity_log_levels_canonicalize_level_prefers_the_trace_marker() -> None:
    from provide.telemetry.logger.processors import canonicalize_level

    assert canonicalize_level(None, "debug", {"level": "debug", "_trace": True})["level"] == "TRACE"
    assert canonicalize_level(None, "debug", {"level": "debug"})["level"] == "DEBUG"
    assert canonicalize_level(None, "warning", {"level": "warning"})["level"] == "WARN"
