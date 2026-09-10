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
import logging
import sys
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from pathlib import Path
    from typing import TextIO

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
from provide.telemetry.logger.handlers import _BackpressureFanoutHandler

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
        set_log_output(cast("TextIO", object()))

    assert log_output_installed() is False


def test_none_is_rejected_rather_than_read_as_a_clear() -> None:
    """``clear_log_output`` is how a writer is removed; None is a mistake."""
    with pytest.raises(ConfigurationError):
        set_log_output(cast("TextIO", None))


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


def test_a_released_writer_stops_receiving_records() -> None:
    """Releasing has to reach the handlers, not only the slot they were built from.

    A host told its writer has been let go is entitled to close it. A child
    handler took the writer when it was built and would go on holding it, so a
    record emitted after teardown would reach a file the host had closed.
    """
    sink = io.StringIO()
    set_log_output(sink)
    configure_logging(_console_config(), force=True)
    import structlog

    structlog.get_logger("probe").info("before-teardown")
    written_by_teardown = sink.getvalue()

    shutdown_logging()
    structlog.get_logger("probe").info("after-teardown")

    assert "before-teardown" in written_by_teardown
    assert "after-teardown" not in sink.getvalue()


def test_a_writer_with_nothing_to_flush_is_released_all_the_same() -> None:
    """``write`` is all a writer owes; buffering is optional and so is flushing."""

    class _MinimalWriter:
        """A sink with no buffer behind it, so no flush to call."""

        def __init__(self) -> None:
            self.written: list[str] = []

        def write(self, text: str) -> int:
            self.written.append(text)
            return len(text)

    set_log_output(cast("TextIO", _MinimalWriter()))

    shutdown_logging()

    assert log_output_installed() is False


def test_a_writer_is_released_even_with_no_pipeline_to_detach_it_from() -> None:
    """A host may install a writer and tear down without ever configuring.

    Nothing holds the writer in that case, so there is nothing to point back at
    the error stream -- but the flush and the release are still owed.
    """
    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers = []
    sink = io.StringIO()
    try:
        set_log_output(sink)

        shutdown_logging()

        assert log_output_installed() is False
    finally:
        root.handlers = saved


def test_retargeting_leaves_a_child_that_is_not_a_plain_stream_alone() -> None:
    """A FileHandler owns a file of its own, which is not this SDK's to redirect."""
    stream_child = logging.StreamHandler(io.StringIO())
    other_child = logging.Handler()
    fanout = _BackpressureFanoutHandler([other_child, stream_child])
    destination = io.StringIO()

    fanout.retarget_stream_children(destination)

    assert stream_child.stream is destination
    assert not hasattr(other_child, "stream")


def test_retargeting_moves_a_child_whose_stream_has_been_closed(tmp_path: Path) -> None:
    """Teardown cannot depend on the outgoing stream still being alive.

    The stream a child holds belongs to whoever supplied it, and a host entitled
    to close its writer leaves the child pointing at a dead file. Flushing a
    closed file raises, and a retarget that flushes before it swaps abandons the
    swap on the way out of that exception -- leaving the child on the dead
    stream, which is the one thing this call exists to prevent.
    """
    dead = (tmp_path / "closed.log").open("w", encoding="utf-8")
    dead.close()
    child = logging.StreamHandler(dead)
    fanout = _BackpressureFanoutHandler([child])
    destination = (tmp_path / "live.log").open("w", encoding="utf-8")
    try:
        fanout.retarget_stream_children(destination)

        assert child.stream is destination
    finally:
        destination.close()


def test_retargeting_flushes_a_live_stream_before_it_lets_go(tmp_path: Path) -> None:
    """What a stream is still holding is owed to it, not to the one taking over.

    Records buffered in the outgoing stream belong in the destination the host
    chose for them. Letting go without a flush would either lose them or land
    them wherever the host's own close happens to put them.
    """
    outgoing_path = tmp_path / "outgoing.log"
    outgoing = outgoing_path.open("w", encoding="utf-8")
    child = logging.StreamHandler(outgoing)
    fanout = _BackpressureFanoutHandler([child])
    destination = (tmp_path / "live.log").open("w", encoding="utf-8")
    try:
        outgoing.write("buffered-before-the-swap")

        fanout.retarget_stream_children(destination)

        assert outgoing_path.read_text(encoding="utf-8") == "buffered-before-the-swap"
    finally:
        outgoing.close()
        destination.close()


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
