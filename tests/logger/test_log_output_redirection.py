# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Where rendered log records go.

Go has carried ``WithLogOutput`` and Rust ``set_log_output`` since 0.10.0;
Python had no equivalent, and the console handler is unconditional, so a host
embedding the Python SDK could neither redirect its records nor capture them
in a test without reaching into internals.

The free-function shape follows Rust's rather than Go's ``SetupOption``:
``setup_telemetry`` takes a config and no options, so there is nothing for an
option to attach to, while ``set_sampling_policy``, ``set_consent_level`` and
ten more like them are already the Python surface for exactly this kind of
process-wide switch.
"""

from __future__ import annotations

import io
import sys

from provide.telemetry.logger.core import _stderr_handler, clear_log_output, set_log_output


def test_by_default_records_go_to_stderr() -> None:
    clear_log_output()

    handler = _stderr_handler()

    assert handler.stream is sys.stderr or getattr(handler.stream, "_stream", None) is sys.stderr


def test_an_installed_writer_receives_the_records() -> None:
    buffer = io.StringIO()
    set_log_output(buffer)
    try:
        handler = _stderr_handler()
        handler.emit(__import__("logging").LogRecord("t", 20, "p", 1, "hello-from-handler", None, None))
        handler.flush()

        assert "hello-from-handler" in buffer.getvalue()
    finally:
        clear_log_output()


def test_clearing_returns_records_to_stderr() -> None:
    buffer = io.StringIO()
    set_log_output(buffer)
    clear_log_output()

    handler = _stderr_handler()

    assert handler.stream is not buffer


def test_the_installed_writer_is_reported() -> None:
    """A host that did not install one must be able to tell."""
    from provide.telemetry.logger.core import log_output_installed

    clear_log_output()
    assert log_output_installed() is False
    buffer = io.StringIO()
    set_log_output(buffer)
    try:
        assert log_output_installed() is True
    finally:
        clear_log_output()
