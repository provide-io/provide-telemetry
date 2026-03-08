# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 MindTenet LLC
# This file is part of Undef Telemetry.
from __future__ import annotations


def setproctitle(_title: str) -> None:
    """No-op mutmut compatibility shim for environments where setproctitle can segfault."""
