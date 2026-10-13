# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Logging from a GC finalizer can re-enter PII sanitization mid-snapshot."""

from __future__ import annotations

import subprocess
import sys

_REENTER_WHILE_COPYING_PATTERNS = """
from provide.telemetry import pii

class ReenterOnSnapshot(list):
    triggered = False

    def __iter__(self):
        if not self.triggered:
            self.triggered = True
            # A GC finalizer can log here while list() allocates under the lock.
            pii.get_secret_patterns()
        return super().__iter__()

pii._custom_secret_patterns = ReenterOnSnapshot()
pii._secret_spans('A' * 20)
"""


def test_secret_snapshot_survives_same_thread_reentry() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _REENTER_WHILE_COPYING_PATTERNS],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    assert result.returncode == 0, result.stderr
