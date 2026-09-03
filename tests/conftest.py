# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import sys
from pathlib import Path

import hypothesis
import pytest
import structlog

from provide.telemetry.backpressure import reset_queues_for_tests
from provide.telemetry.cardinality import clear_cardinality_limits
from provide.telemetry.consent import _reset_consent_for_tests
from provide.telemetry.logger.context import clear_context
from provide.telemetry.logger.core import _reset_logging_for_tests
from provide.telemetry.resilience import reset_resilience_for_tests
from provide.telemetry.runtime import reset_runtime_for_tests
from provide.telemetry.sampling import reset_sampling_for_tests
from provide.telemetry.setup import _reset_setup_state_for_tests
from provide.telemetry.tracing.context import set_trace_context

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# Hypothesis measures how long each example takes and fails the test at 200ms by
# default. That deadline asks a question this suite never runs in a position to
# answer: the property tests execute under coverage in the normal gate and under
# mutmut's trampoline in the mutation gate, where every call is dispatched
# through a wrapper, and a run slow enough to trip the deadline says something
# about the instrumentation rather than about the code.
#
# Left on, it produced a flake with no logic behind it. The mutation gate's
# stats collection failed once on
# test_event_name_property_builds_valid_strict_name — a property that cannot
# fail on any input its strategy can generate, since `[a-z][a-z0-9_]{0,15}` is a
# subset of the strict segment grammar and 3-5 segments is exactly the accepted
# range. Seven full-suite reruns across 3.11 and 3.13 could not reproduce it,
# and no falsifying example was stored, because there was none to store: a
# DeadlineExceeded reports a perfectly valid example and reads like a logic
# failure.
#
# Timing regressions are caught by the performance gates, which measure without
# instrumentation and have baselines to compare against.
hypothesis.settings.register_profile("provide", deadline=None)
hypothesis.settings.load_profile("provide")


@pytest.fixture(autouse=True)
def reset_logger_state() -> None:
    """Reset structlog and logger core state before each test.

    Tests that call configure_logging() directly mutate structlog's global
    pipeline configuration.  Without a reset, a test that installs a local
    helper class as a processor can leave a broken pipeline for the next test
    that runs in the same xdist worker — even though monkeypatch restores the
    *attribute* it was patched on, the already-configured processor list
    retains a reference to the local object.

    Sampling and resilience policies are also reset here. Without that, a test
    that sets a signal's sampling rate to 0.0 would cause apply_sampling to
    drop all events in the next test, and a test that trips the logs circuit
    breaker would cause later logger tests to fail-open and skip OTLP setup.

    setup_telemetry()'s setup latch is also cleared here. Without that,
    a previous test can leave setup marked complete even after conftest resets
    structlog/runtime state, causing later setup_telemetry(config) calls to
    no-op and get_logger() to lazily rebuild logging from env defaults.

    The published lifecycle generation is also cleared: processors that read live config
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
    reset_resilience_for_tests()
    reset_runtime_for_tests()
    reset_queues_for_tests()
    _reset_consent_for_tests()
    clear_cardinality_limits()
    # Bound log context is a contextvar, so a test that binds request_id or
    # session_id and does not clear it leaks into every later test in the same
    # worker. merge_runtime_context does event_dict.update(get_context()), so
    # the stale value *overwrites* the later test's own field — which is how a
    # macOS CI worker turned request_id="abc" into "rid" four tests later.
    clear_context()


@pytest.fixture(autouse=True)
def reset_trace_context() -> None:
    """Reset trace context before each test.

    Mutmut's stats collection runs without xdist (single process, sequential),
    so contextvar state from one test leaks to the next when a mutant prevents
    cleanup.  This fixture ensures a clean slate for every test.
    """
    set_trace_context(None, None)
