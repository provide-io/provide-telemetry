# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""What a host is owed once it hands this SDK a writer.

``log_output`` in spec/telemetry-api.yaml states the contract: colour follows
the sink rather than the process, a sink supplied but unusable is a
configuration error rather than a silent fall back to the error stream, and
shutdown flushes it. Go and Rust reach all three by opposite routes -- Go by
probing and validating, Rust by taking the conservative answer -- and Python
reaches them here.
"""

from __future__ import annotations

import io
import sys

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.exceptions import ConfigurationError
from provide.telemetry.logger.core import (
    _reset_logging_for_tests,
    clear_log_output,
    configure_logging,
    log_output_installed,
    set_log_output,
    shutdown_logging,
)

ESC = "\x1b"


class _TerminalStream(io.StringIO):
    """A stream that claims to be a terminal, as a console stream would."""

    def isatty(self) -> bool:
        return True


def _stderr_as_a_terminal(monkeypatch: pytest.MonkeyPatch) -> _TerminalStream:
    """Stand a terminal in for stderr, from inside the test body.

    Not a fixture: pytest re-installs its capture streams between the setup and
    call phases, so a ``sys.stderr`` patched during setup is overwritten before
    the test runs and the test silently asserts against pytest's own stream.
    """
    stream = _TerminalStream()
    monkeypatch.setattr(sys, "stderr", stream)
    return stream


def _console_config() -> TelemetryConfig:
    return TelemetryConfig.from_env({"PROVIDE_LOG_FORMAT": "console"})


def test_a_sink_that_is_not_a_terminal_gets_no_ansi(monkeypatch: pytest.MonkeyPatch) -> None:
    """The invariant the spec states: ANSI never reaches a destination not known to render it."""
    _stderr_as_a_terminal(monkeypatch)
    sink = io.StringIO()
    set_log_output(sink)
    try:
        configure_logging(_console_config(), force=True)
        import structlog

        structlog.get_logger("probe").info("hello")

        assert ESC not in sink.getvalue()
        assert "hello" in sink.getvalue()
    finally:
        clear_log_output()


def test_a_terminal_still_gets_colour_when_no_sink_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Asking the sink must not cost the ordinary path its colour."""
    stderr = _stderr_as_a_terminal(monkeypatch)
    clear_log_output()
    configure_logging(_console_config(), force=True)
    import structlog

    structlog.get_logger("probe").info("hello")

    assert ESC in stderr.getvalue()


def test_a_sink_that_is_a_terminal_keeps_its_colour() -> None:
    """Following the sink means both answers, not only the cautious one."""
    sink = _TerminalStream()
    set_log_output(sink)
    try:
        configure_logging(_console_config(), force=True)
        import structlog

        structlog.get_logger("probe").info("hello")

        assert ESC in sink.getvalue()
    finally:
        clear_log_output()


def test_a_writer_without_write_is_a_configuration_error() -> None:
    """A host that asked for its logs elsewhere must not find them on stderr."""
    with pytest.raises(ConfigurationError):
        set_log_output(object())  # type: ignore[arg-type]

    assert log_output_installed() is False


def test_none_is_rejected_rather_than_read_as_a_clear() -> None:
    """``clear_log_output`` is how a writer is removed; None is a mistake."""
    with pytest.raises(ConfigurationError):
        set_log_output(None)  # type: ignore[arg-type]


def test_shutdown_flushes_and_releases_the_writer() -> None:
    """The host is entitled to everything written to the writer it supplied."""
    flushed: list[bool] = []

    class _Writer(io.StringIO):
        def flush(self) -> None:
            flushed.append(True)
            super().flush()

    set_log_output(_Writer())
    configure_logging(_console_config(), force=True)

    shutdown_logging()

    assert flushed
    assert log_output_installed() is False


def test_a_flush_that_raises_does_not_break_shutdown() -> None:
    """A host that closed its writer must not turn teardown into an exception."""

    class _ClosedWriter(io.StringIO):
        def flush(self) -> None:
            raise ValueError("I/O operation on closed file")

        def write(self, s: str) -> int:  # pragma: no cover - never reached
            return 0

    set_log_output(_ClosedWriter())

    shutdown_logging()

    assert log_output_installed() is False


def test_installing_after_setup_takes_effect_without_a_reconfigure() -> None:
    """The timing half of the contract: an ambient switch is effective at once."""
    configure_logging(_console_config(), force=True)
    sink = io.StringIO()
    set_log_output(sink)
    try:
        import structlog

        structlog.get_logger("probe").info("after-setup")

        assert "after-setup" in sink.getvalue()
    finally:
        clear_log_output()


def test_clearing_after_setup_returns_records_to_the_error_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    stderr = _stderr_as_a_terminal(monkeypatch)
    sink = io.StringIO()
    configure_logging(_console_config(), force=True)
    set_log_output(sink)
    clear_log_output()

    import structlog

    structlog.get_logger("probe").info("back-to-stderr")

    assert "back-to-stderr" not in sink.getvalue()
    assert "back-to-stderr" in stderr.getvalue()


def test_the_test_reset_releases_an_installed_writer() -> None:
    """A sink is process-global; a test that installs one must not leak it."""
    set_log_output(io.StringIO())

    _reset_logging_for_tests()

    assert log_output_installed() is False
