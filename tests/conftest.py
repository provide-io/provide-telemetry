# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import structlog

from provide.telemetry.backpressure import reset_queues_for_tests
from provide.telemetry.cardinality import clear_cardinality_limits
from provide.telemetry.consent import _reset_consent_for_tests
from provide.telemetry.logger.core import _reset_logging_for_tests
from provide.telemetry.runtime import reset_runtime_for_tests
from provide.telemetry.sampling import reset_sampling_for_tests
from provide.telemetry.setup import _reset_setup_state_for_tests
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

    Sampling policies are also reset here: a test that sets a signal's rate to
    0.0 (e.g. test_rate_zero_never_samples) would cause apply_sampling to drop
    all events in the next test on the same worker, producing empty log output.

    setup_telemetry()'s _setup_done latch is also cleared here. Without that,
    a previous test can leave setup marked complete even after conftest resets
    structlog/runtime state, causing later setup_telemetry(config) calls to
    no-op and get_logger() to lazily rebuild logging from env defaults.

    Runtime _active_config is also cleared: processors that read live config
    (harden_input, sanitize_sensitive_fields, enforce_event_schema) would
    otherwise pick up a previous test's TelemetryConfig and ignore the
    constructor-captured values, breaking property tests that specify tight
    bounds like max_attr_value_length=100.

    Cardinality limits are cleared so a prior test that registered a low
    max_values cap on an attribute key cannot leak into later tests via
    the guarded metric attribute rewrite to '__overflow__'. Under xdist
    this rarely surfaces (each worker has its own process), but mutmut
    runs tests sequentially in one process so state leaks do bite.
    """
    structlog.reset_defaults()
    _reset_logging_for_tests()
    _reset_setup_state_for_tests()
    reset_sampling_for_tests()
    reset_runtime_for_tests()
    reset_queues_for_tests()
    _reset_consent_for_tests()
    clear_cardinality_limits()


@pytest.fixture(autouse=True)
def reset_trace_context() -> None:
    """Reset trace context before each test.

    Mutmut's stats collection runs without xdist (single process, sequential),
    so contextvar state from one test leaks to the next when a mutant prevents
    cleanup.  This fixture ensures a clean slate for every test.
    """
    set_trace_context(None, None)
