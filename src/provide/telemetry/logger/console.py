# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""What the destination stream can actually render.

Two questions this SDK used to answer by assumption, and got wrong on Windows in
both directions.

**Encoding.** CPython writes to a console through ``WriteConsoleW``, so a
console renders whatever it is given regardless of its code page. A *redirected*
stream is different: on Windows it carries the locale encoding — cp1252 on a
Western install, not UTF-8, on every version this package supports, since PEP
686 makes UTF-8 the default only in 3.15. stderr is given
``errors="backslashreplace"``, so an emoji does not raise there; it is written
out as the literal text ``\\U0001f439``. Nothing fails and nothing is reported.
A parent process capturing the stream — the case this SDK exists to serve when
several language runtimes share one log — reads mangled records.

**ANSI.** A Windows console renders escape sequences only once
``ENABLE_VIRTUAL_TERMINAL_PROCESSING`` is set on its handle. Windows Terminal
and current conhost set it themselves; legacy conhost does not, and prints
``ESC[36m`` literally. Deciding colour from ``isatty()`` alone therefore put
escapes on the one platform least able to render them.

structlog adds a third condition of its own: ``ConsoleRenderer(colors=True)``
raises ``SystemError`` on Windows when colorama is not installed, and colorama
is not a dependency of this package. ``configure_logging`` catches every
exception and falls back, so on a Windows terminal without colorama the entire
pipeline — context, OTel, levels — was silently replaced by a WARNING-level
stderr fallback. See ``windows_console`` in ``spec/telemetry-api.yaml``.
"""

from __future__ import annotations

import importlib.util
import sys
from typing import IO, Any

from provide.telemetry.logger._windows_console import enable_virtual_terminal

__all__ = ["ansi_supported", "structlog_colors", "utf8_writer"]

# CPython spells the one codec several ways depending on how the stream was
# configured; a hyphen and an underscore are the same separator to it.
_UTF8_NAMES = frozenset({"utf8", "utf_8"})


# Windows console API constants, used only inside _enable_virtual_terminal.
# Nothing on a non-Windows runner can observe them, so a mutation of either is
# undetectable by construction rather than by a gap in the tests.
def _is_windows() -> bool:
    return sys.platform == "win32"


# Bound as a module attribute so a test can substitute it: the interop it names
# cannot run on the machine that checks this file. See _windows_console, which
# also explains why it lives in a module of its own.
_enable_virtual_terminal = enable_virtual_terminal


def _colorama_installed() -> bool:
    """Whether structlog's Windows colour dependency can be imported."""
    if "colorama" in sys.modules:
        return True
    return importlib.util.find_spec("colorama") is not None


def ansi_supported(stream: Any) -> bool:
    """Whether ANSI escapes written to stream will be rendered as escapes.

    A file or a pipe never renders them. A terminal does — except on Windows,
    where it does only once virtual-terminal processing is enabled, so there the
    answer is whether enabling it worked.
    """
    if not _isatty(stream):
        return False
    if not _is_windows():
        return True
    return _enable_virtual_terminal(stream)


def structlog_colors(stream: Any) -> bool:
    """``ansi_supported``, plus structlog's own requirement.

    ``structlog.dev.ConsoleRenderer(colors=True)`` raises ``SystemError`` on
    Windows without colorama rather than degrading, and that exception costs the
    whole logging configuration. Answering no is the difference between plain
    output and no pipeline.
    """
    if not ansi_supported(stream):
        return False
    if not _is_windows():
        return True
    return _colorama_installed()


def utf8_writer(stream: Any) -> Any:
    """stream, or a writer over its byte layer that always emits UTF-8.

    Returned unchanged whenever it already encodes UTF-8, or has no byte layer
    to write to — a host that substituted a plain text sink keeps it, since
    replacing the host's stream outright is a larger liberty than the mangling
    it would fix.
    """
    encoding = getattr(stream, "encoding", None)
    if not isinstance(encoding, str):
        return stream
    if encoding.replace("-", "_").lower() in _UTF8_NAMES:
        return stream
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        return stream
    return _Utf8Writer(stream, buffer)


def _isatty(stream: Any) -> bool:
    isatty = getattr(stream, "isatty", None)
    if isatty is None:
        return False
    try:
        return bool(isatty())
    except (OSError, ValueError):
        return False


class _Utf8Writer:
    """Writes text to a stream's byte layer as UTF-8, whatever the text layer's
    encoding is.

    Only the two methods ``logging.StreamHandler`` and structlog's
    ``PrintLogger`` call are real work; ``isatty`` is here because the colour
    and terminal probes ask the writer, and the honest answer belongs to the
    stream underneath.
    """

    def __init__(self, stream: Any, buffer: IO[bytes]) -> None:
        self._stream = stream
        self._buffer = buffer

    def write(self, text: str) -> int:
        # The host writes through the text layer and this writes under it, so
        # the text layer is drained first: two layers over one descriptor
        # interleave in whatever order they flush.
        _quiet_flush(self._stream)
        self._buffer.write(text.encode("utf-8", "backslashreplace"))
        return len(text)

    def flush(self) -> None:
        _quiet_flush(self._buffer)

    def isatty(self) -> bool:
        return _isatty(self._stream)


def _quiet_flush(target: Any) -> None:
    """Flush target, tolerating a stream that has already been closed.

    Logging outlives most things in a shutting-down process, and a flush that
    raises inside a handler becomes a traceback on stderr in place of the record
    the caller asked for.
    """
    flush = getattr(target, "flush", None)
    if flush is None:
        return
    try:
        flush()
    except (OSError, ValueError):
        return
