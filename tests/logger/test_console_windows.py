# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The two ways Windows silently broke this SDK's output.

Both are invisible on Linux and neither raises, which is why they survived every
gate: one mangles non-ASCII into escape text, the other drops the whole logging
pipeline to an emergency fallback.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from typing import Any

import pytest

from provide.telemetry.logger import console


class _Stream:
    """A text stream with a byte buffer, like sys.stderr has.

    Deliberately not an io.TextIOBase subclass: the base declares `encoding` as
    a writeable attribute, and the point of these doubles is to control it.
    utf8_writer duck-types what it needs, which is exactly what this offers.
    """

    def __init__(self, *, encoding: str, tty: bool, buffer: io.BytesIO | None = None, fileno: int | None = 2) -> None:
        self.encoding = encoding
        self._tty = tty
        self._fileno = fileno
        self.buffer: Any = buffer if buffer is not None else io.BytesIO()
        self.text: list[str] = []
        self.flushes = 0

    def isatty(self) -> bool:
        return self._tty

    def fileno(self) -> int:
        if self._fileno is None:
            raise io.UnsupportedOperation("fileno")
        return self._fileno

    def write(self, text: str) -> int:
        self.text.append(text)
        return len(text)

    def flush(self) -> None:
        self.flushes += 1


class _BufferlessStream:
    """A stream a host substituted that offers no byte layer at all."""

    def __init__(self, *, encoding: str = "cp1252") -> None:
        self.encoding = encoding
        self.text: list[str] = []

    def isatty(self) -> bool:
        return False

    def write(self, text: str) -> int:
        self.text.append(text)
        return len(text)


# ── UTF-8 output ─────────────────────────────────────────────────────────────


def test_a_utf8_stream_is_handed_back_unchanged() -> None:
    """Nothing is wrapped when the destination already encodes UTF-8."""
    stream = _Stream(encoding="utf-8", tty=False)
    assert console.utf8_writer(stream) is stream


def test_a_utf8_alias_is_recognised() -> None:
    """CPython spells it several ways depending on how it was configured."""
    for spelling in ("UTF-8", "utf8", "UTF8", "utf_8"):
        stream = _Stream(encoding=spelling, tty=False)
        assert console.utf8_writer(stream) is stream, spelling


def test_a_non_utf8_stream_is_wrapped_and_emits_utf8_bytes() -> None:
    """The defect: a redirected stream on Windows is cp1252.

    CPython gives stderr ``errors="backslashreplace"``, so an emoji does not
    raise — it is written out as the literal text ``\\U0001f439``. Nothing fails,
    nothing is logged about it, and the record is mangled by the time anything
    downstream reads it.
    """
    stream = _Stream(encoding="cp1252", tty=False)
    writer = console.utf8_writer(stream)
    assert writer is not stream

    writer.write("hamster 🐹\n")
    writer.flush()

    assert stream.buffer.getvalue() == "hamster 🐹\n".encode()
    assert stream.text == [], "the text layer was written to as well as the byte layer"


def test_the_wrapper_flushes_the_text_layer_before_writing_bytes() -> None:
    """Ordering. Two layers over one file descriptor interleave by whoever
    flushes last, and the host writes through the text layer."""
    stream = _Stream(encoding="cp1252", tty=False)
    writer = console.utf8_writer(stream)

    writer.write("first\n")

    assert stream.flushes >= 1, "the text layer was not drained before bytes went out"


def test_the_wrapper_reports_the_underlying_stream_as_a_terminal() -> None:
    """Colour and the callsite both ask; the answer belongs to the real stream."""
    stream = _Stream(encoding="cp1252", tty=True)
    assert console.utf8_writer(stream).isatty() is True


def test_a_stream_without_a_byte_layer_is_left_alone() -> None:
    """A host that substituted a plain text sink keeps it.

    There is no byte layer to write UTF-8 into, and replacing the host's stream
    with one of our own would be a larger liberty than the mangling it fixes.
    """
    stream = _BufferlessStream()
    assert console.utf8_writer(stream) is stream


def test_a_stream_with_no_encoding_attribute_is_left_alone() -> None:
    """io.StringIO and the capture streams tests hand in have none."""
    stream = io.StringIO()
    assert console.utf8_writer(stream) is stream


def test_the_wrapper_replaces_what_it_cannot_encode_rather_than_raising() -> None:
    """A logger that raises takes the caller's request with it."""
    stream = _Stream(encoding="cp1252", tty=False)
    writer = console.utf8_writer(stream)

    writer.write("lone surrogate \udcff\n")

    assert stream.buffer.getvalue().startswith(b"lone surrogate ")


# ── ANSI ─────────────────────────────────────────────────────────────────────


def test_ansi_is_off_for_a_stream_that_is_not_a_terminal() -> None:
    assert console.ansi_supported(_Stream(encoding="utf-8", tty=False)) is False


def test_ansi_is_on_for_a_terminal_away_from_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert console.ansi_supported(_Stream(encoding="utf-8", tty=True)) is True


def test_ansi_on_windows_follows_virtual_terminal_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Windows console renders escapes only once VT is enabled on it.

    Legacy conhost refuses, and prints the escape literally. Reporting colour
    from "is a terminal" alone put those escapes on the one platform least able
    to render them.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    stream = _Stream(encoding="utf-8", tty=True)

    monkeypatch.setattr(console, "_enable_virtual_terminal", lambda _fd: True)
    assert console.ansi_supported(stream) is True

    monkeypatch.setattr(console, "_enable_virtual_terminal", lambda _fd: False)
    assert console.ansi_supported(stream) is False


def test_virtual_terminal_is_not_attempted_for_a_pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    """No console, nothing to enable."""
    monkeypatch.setattr(sys, "platform", "win32")

    def _fail(_fd: int) -> bool:
        raise AssertionError("VT was attempted on a stream that is not a terminal")

    monkeypatch.setattr(console, "_enable_virtual_terminal", _fail)
    assert console.ansi_supported(_Stream(encoding="utf-8", tty=False)) is False


# ── structlog's own Windows requirement ──────────────────────────────────────


def test_structlog_colors_match_ansi_away_from_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert console.structlog_colors(_Stream(encoding="utf-8", tty=True)) is True
    assert console.structlog_colors(_Stream(encoding="utf-8", tty=False)) is False


def test_structlog_colors_are_off_on_windows_without_colorama(monkeypatch: pytest.MonkeyPatch) -> None:
    """structlog.dev.ConsoleRenderer(colors=True) raises SystemError there.

    configure_logging catches every exception and drops to the emergency
    pipeline, so the whole logging configuration — context, OTel, levels — was
    silently replaced by a WARNING-level stderr fallback on any Windows terminal
    where colorama happened not to be installed. It is not a dependency of this
    package.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(console, "_enable_virtual_terminal", lambda _fd: True)
    monkeypatch.setattr(console, "_colorama_installed", lambda: False)

    assert console.structlog_colors(_Stream(encoding="utf-8", tty=True)) is False


def test_structlog_colors_are_on_on_windows_with_colorama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(console, "_enable_virtual_terminal", lambda _fd: True)
    monkeypatch.setattr(console, "_colorama_installed", lambda: True)

    assert console.structlog_colors(_Stream(encoding="utf-8", tty=True)) is True


def test_colorama_availability_is_answered_by_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real check, not the stub the tests above install."""
    monkeypatch.setitem(sys.modules, "colorama", object())
    assert console._colorama_installed() is True

    monkeypatch.delitem(sys.modules, "colorama", raising=False)
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    assert console._colorama_installed() is False


# ── streams that are gone, or were never streams ─────────────────────────────


class _Closed:
    """A stream after the interpreter has torn its file object down."""

    encoding = "cp1252"

    def fileno(self) -> int:
        raise ValueError("I/O operation on closed file")

    # Declared rather than attached, so both type checkers can see it: one test
    # gives this a live byte layer to prove the record still reaches it.
    buffer: Any = None

    def isatty(self) -> bool:
        raise ValueError("I/O operation on closed file")

    def flush(self) -> None:
        raise ValueError("I/O operation on closed file")


def test_a_closed_stream_is_not_a_terminal() -> None:
    """Asked during shutdown, after the host closed its own stderr."""
    assert console._isatty(_Closed()) is False


def test_an_object_with_no_isatty_is_not_a_terminal() -> None:
    """A host can pass anything with a write method as its log destination."""
    assert console._isatty(object()) is False


def test_flushing_a_closed_stream_is_not_an_error() -> None:
    """A flush that raises inside a handler replaces the record with a
    traceback, which is a worse answer than a record that did not land."""
    console._quiet_flush(_Closed())


def test_flushing_something_with_no_flush_is_not_an_error() -> None:
    console._quiet_flush(object())


def test_the_wrapper_still_writes_when_the_text_layer_cannot_flush() -> None:
    """The byte layer is the one that matters; a dead text layer must not stop
    the record reaching it."""
    buffer = io.BytesIO()
    stream = _Closed()
    stream.buffer = buffer

    writer = console.utf8_writer(stream)
    writer.write("still here 🐹\n")

    assert buffer.getvalue() == "still here 🐹\n".encode()


# ── the wiring ───────────────────────────────────────────────────────────────


def test_the_stderr_handler_writes_through_the_utf8_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The seam has to be *used*; the helpers above prove only that it works."""
    from provide.telemetry.logger import core

    stream = _Stream(encoding="cp1252", tty=False)
    monkeypatch.setattr(sys, "stderr", stream)

    handler = core._stderr_handler()
    handler.stream.write("hamster 🐹\n")

    assert stream.buffer.getvalue() == "hamster 🐹\n".encode()


def test_the_stderr_handler_keeps_a_utf8_stream_as_it_is(monkeypatch: pytest.MonkeyPatch) -> None:
    """Which is every stream off Windows, so nothing changes there."""
    from provide.telemetry.logger import core

    stream = _Stream(encoding="utf-8", tty=False)
    monkeypatch.setattr(sys, "stderr", stream)

    assert core._stderr_handler().stream is stream


def test_a_renderer_that_demands_colorama_does_not_cost_the_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole defect, end to end.

    structlog raises SystemError from ConsoleRenderer when colours are asked for
    on Windows without colorama. configure_logging catches every exception, so
    that raise replaced the entire configuration — context, OTel, module levels
    — with the WARNING-level emergency fallback, leaving one RuntimeWarning
    behind.

    The stand-in raises on exactly the condition structlog does, so this fails
    if the colour decision ever stops consulting console.structlog_colors.
    """
    import structlog

    from provide.telemetry.config import TelemetryConfig
    from provide.telemetry.logger import core

    real_renderer = structlog.dev.ConsoleRenderer

    def _renderer(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("colors"):
            raise SystemError("ConsoleRenderer with `colors=True` on Windows requires the colorama package installed.")
        return real_renderer(*args, **kwargs)

    monkeypatch.setattr(structlog.dev, "ConsoleRenderer", _renderer)
    monkeypatch.setattr(core, "structlog_colors", lambda _stream: False)

    fallbacks: list[BaseException] = []
    monkeypatch.setattr(core, "_setup_emergency_fallback", lambda exc: fallbacks.append(exc))

    config = TelemetryConfig.from_env()
    config.logging.fmt = "console"
    core.configure_logging(config, force=True)

    assert fallbacks == [], f"configuration was abandoned: {fallbacks}"


def test_the_pipeline_really_would_be_lost_without_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of the pair: with colours asked for, it does fall back.

    Without this, the test above would pass just as well against a build that
    never asks for colours at all, and would stop being about the defect.
    """
    import structlog

    from provide.telemetry.config import TelemetryConfig
    from provide.telemetry.logger import core

    def _renderer(*_args: Any, **kwargs: Any) -> Any:
        if kwargs.get("colors"):
            raise SystemError("requires the colorama package installed.")
        raise AssertionError("colours were not requested, so the defect cannot be reproduced")

    monkeypatch.setattr(structlog.dev, "ConsoleRenderer", _renderer)
    monkeypatch.setattr(core, "structlog_colors", lambda _stream: True)

    fallbacks: list[BaseException] = []
    monkeypatch.setattr(core, "_setup_emergency_fallback", lambda exc: fallbacks.append(exc))

    config = TelemetryConfig.from_env()
    config.logging.fmt = "console"
    core.configure_logging(config, force=True)

    assert len(fallbacks) == 1
    assert isinstance(fallbacks[0], SystemError)


def test_a_terminal_with_no_descriptor_is_taken_at_its_word(monkeypatch: pytest.MonkeyPatch) -> None:
    """The case that broke the pretty renderer's tests on Windows.

    A StringIO subclass reporting isatty() is how this repo — and plenty of
    hosts — stand in for a terminal. It has no descriptor, and an earlier
    version fell back to descriptor 2, which asked the *process's* stderr
    whether somebody else's object renders ANSI. On the Windows runner that
    stderr is a pipe, so the answer was no and the colours vanished.
    """
    monkeypatch.setattr(sys, "platform", "win32")

    def _fail(_fd: int) -> bool:
        raise AssertionError("VT was attempted for a stream that has no descriptor")

    monkeypatch.setattr(console, "_enable_virtual_terminal", _fail)
    assert console.ansi_supported(_Stream(encoding="utf-8", tty=True, fileno=None)) is True


def test_a_terminal_with_a_descriptor_has_it_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """And when there is one, that is what the interop is asked about."""
    monkeypatch.setattr(sys, "platform", "win32")
    seen: list[int] = []

    def _record(fd: int) -> bool:
        seen.append(fd)
        return True

    monkeypatch.setattr(console, "_enable_virtual_terminal", _record)
    assert console.ansi_supported(_Stream(encoding="utf-8", tty=True, fileno=7)) is True
    assert seen == [7]


def test_a_descriptor_that_raises_is_treated_as_absent() -> None:
    """A closed stream answers isatty and then refuses fileno."""
    assert console._fileno(_Closed()) is None


def test_an_object_with_no_fileno_has_no_descriptor() -> None:
    assert console._fileno(object()) is None
