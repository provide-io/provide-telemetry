# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Where rendered log records go.

Python's console handler is built unconditionally and ``configure_logging``
takes the root logger with ``basicConfig(force=True)``, so the destination is
out of the host's reach once setup returns -- the same position Go's handler
chain and Rust's ``eprintln!`` put their runtimes in, arrived at from the other
direction. A host that wants to tee its records, prefix them where several
language runtimes share one stream, or drop them, installs a writer here.

The terms are ``log_output`` in spec/telemetry-api.yaml, and they are the same
four Go and Rust meet: a writer that cannot be written to is refused rather than
ignored, colour follows the writer rather than the process, shutdown drains it,
and installing one applies to the next record rather than the next
reconfiguration.

A module of its own, mirroring rust/src/logger/sink.rs, because the slot is
process-global state with its own lock and its own lifecycle, answerable to a
host rather than to a config.
"""

from __future__ import annotations

import contextlib
import sys
import threading
from typing import TextIO

from provide.telemetry.exceptions import ConfigurationError

__all__ = [
    "clear_log_output",
    "installed_writer",
    "log_destination",
    "log_output_installed",
    "release_log_output",
    "set_log_output",
]

# None means stderr, which is what a process that says nothing gets. Guarded by
# its own lock rather than the logger's config lock: a host may install a writer
# at any point, including from a thread that is not the one configuring
# telemetry.
_LOG_OUTPUT: TextIO | None = None
_LOG_OUTPUT_LOCK = threading.Lock()


def _validate_writer(writer: TextIO) -> None:
    """Refuse a writer nothing can be written to.

    A sink that is supplied but unusable is a configuration error rather than a
    silent fall back to the error stream: a host that asked for its logs
    elsewhere must not find them on a stream it is not reading. Go rejects a nil
    writer before installing it and Rust cannot be handed one; the equivalent
    here is a writer whose ``write`` is missing or is not callable.

    ``None`` is included in that, deliberately. ``clear_log_output`` is how a
    writer is removed, so a ``None`` arriving here is a variable that never got
    its value rather than an instruction.
    """
    if not callable(getattr(writer, "write", None)):
        raise ConfigurationError(f"set_log_output: {type(writer).__name__} has no write() to send records to")


def _detach() -> None:
    """Stop the live handlers writing to a writer that has been let go.

    Lazily imported for the same reason as the rebuild below.
    """
    from provide.telemetry.logger.core import detach_log_writer

    detach_log_writer()


def _reapply() -> None:
    """Rebuild the logging pipeline so a change of destination is effective at once.

    The destination reaches a record through two things built at configuration
    time: the handler's stream, and the renderer's colour answer, which follows
    the destination rather than the process. Swapping the stream alone would
    leave a file rendering with the terminal's answer, so the pipeline is rebuilt
    rather than patched.

    Imported here rather than at module scope because the logger's core imports
    this module for the slot; the dependency runs one way at import time and the
    other only when a host changes destination.
    """
    from provide.telemetry.logger.core import reapply_log_output

    reapply_log_output()


def set_log_output(writer: TextIO) -> None:
    """Send rendered log records to *writer* instead of stderr.

    Effective at once, whether or not the SDK has been configured: a host that
    installs a writer is asking for the records it has not seen yet, not for the
    ones after some later reconfiguration. Colour follows the writer, so a file
    or a pipe receives no ANSI even from a process whose stderr is a terminal.

    Raises ``ConfigurationError`` for a writer that cannot be written to.
    """
    global _LOG_OUTPUT
    _validate_writer(writer)
    with _LOG_OUTPUT_LOCK:
        _LOG_OUTPUT = writer
    # Outside the lock: rebuilding reaches the handler factory, which takes it.
    _reapply()


def clear_log_output() -> None:
    """Return rendered log records to stderr, dropping any installed writer."""
    global _LOG_OUTPUT
    with _LOG_OUTPUT_LOCK:
        _LOG_OUTPUT = None
    _reapply()


def log_output_installed() -> bool:
    """Whether a host has installed a writer."""
    return installed_writer() is not None


def installed_writer() -> TextIO | None:
    """The writer a host installed, or ``None`` for a process that said nothing.

    Distinct from ``log_destination`` because the handler factory needs the
    difference: a writer the host chose is taken as given, while stderr is the
    stream this process did not choose and is wrapped accordingly.
    """
    with _LOG_OUTPUT_LOCK:
        return _LOG_OUTPUT


def log_destination() -> TextIO:
    """Where rendered records land, which is what decides colour.

    ``ansi_supported`` asks a stream whether it is a terminal, so a writer the
    host installed answers for itself: a file or a buffer says no and receives no
    escapes. Python can afford the question where Rust cannot -- every file
    object carries ``isatty`` -- so this is Go's answer rather than Rust's
    conservative one.
    """
    installed = installed_writer()
    return installed if installed is not None else sys.stderr


def release_log_output() -> None:
    """Flush the installed writer and let it go.

    The host handed over a writer and is entitled to everything written to it, so
    a buffered writer is drained before it is dropped. A writer the host has
    already closed raises on flush; teardown is not the place to surface that,
    and there is nowhere to report it to.

    Released because the runtime that was given the writer is the one being torn
    down, which is what Rust's shutdown does with its own. Handlers already
    built are pointed back at the error stream rather than rebuilt: the
    configuration a rebuild would reconstruct is being dismantled by the same
    call, and a handler still holding the writer would leave "released" meaning
    only that the slot was cleared.
    """
    global _LOG_OUTPUT
    with _LOG_OUTPUT_LOCK:
        writer = _LOG_OUTPUT
        _LOG_OUTPUT = None
    if writer is None:
        return
    # Before the flush, so nothing lands in the writer between draining it and
    # the host taking it back.
    _detach()
    flush = getattr(writer, "flush", None)
    if callable(flush):
        with contextlib.suppress(Exception):
            flush()
