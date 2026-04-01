# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import structlog

from provide.telemetry.logger.core import _reset_logging_for_tests
from provide.telemetry.sampling import reset_sampling_for_tests
from provide.telemetry.tracing.context import set_trace_context

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def reset_logger_state() -> None:
    """Reset structlog and logger core state before each test.

    Tests that call configure_logging() directly mutate structlog's global
    pipeline configuration.  Without a reset, a test that installs a local
    helper class as a processor can leave a broken pipeline for the next test
    that runs in the same xdist worker — even though monkeypatch restores the
    *attribute* it was patched on, the already-configured processor list
    retains a reference to the local object.
    """
    structlog.reset_defaults()
    _reset_logging_for_tests()
