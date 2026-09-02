# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The one thing this SDK asks of a Windows console, isolated.

A console renders ANSI escapes only once ``ENABLE_VIRTUAL_TERMINAL_PROCESSING``
is set on its handle. Windows Terminal and current conhost set it themselves;
legacy conhost does not and prints ``ESC[36m`` literally, which is why colour is
reported from whether enabling it succeeded rather than from the stream being a
terminal — every console is one.

Its own module, and named in ``do_not_mutate``, for the reason
``tracing/context_runtime.py`` is: the coverage and mutation runs are Linux, and
nothing here can execute there, so every mutant of it survives by construction
rather than through a gap in the tests. Splitting it keeps the rest of
``console.py`` — the decisions, which are the part that was wrong — fully
mutated.

Stated plainly: **no automated test exercises this function.** What is tested,
in ``tests/logger/test_console_windows.py`` with this substituted, is that it is
asked only for a Windows terminal, and that its answer is the colour answer.
"""

from __future__ import annotations

import sys
from typing import Any

__all__ = ["enable_virtual_terminal"]

_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 4
_STD_ERROR_HANDLE = -12
_STD_OUTPUT_HANDLE = -11


def enable_virtual_terminal(stream: Any) -> bool:  # pragma: no cover — Windows-only interop
    """Turn on VT processing for stream's console handle, reporting success."""
    import ctypes

    # Narrowed rather than suppressed. typeshed declares ctypes.windll only for
    # win32, so an ignore comment is required off Windows and *unused* on it —
    # and warn_unused_ignores makes that an error there. Restating the platform
    # test the caller already made lets both type checkers resolve windll on
    # Windows and treat the rest as unreachable everywhere else.
    if sys.platform != "win32":
        return False

    kernel32 = ctypes.windll.kernel32
    try:
        fileno = stream.fileno()
    except (AttributeError, OSError, ValueError):
        fileno = 2
    handle = kernel32.GetStdHandle(_STD_ERROR_HANDLE if fileno == 2 else _STD_OUTPUT_HANDLE)

    mode = ctypes.c_uint32()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return False
    if mode.value & _ENABLE_VIRTUAL_TERMINAL_PROCESSING:
        return True
    return bool(kernel32.SetConsoleMode(handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING))
